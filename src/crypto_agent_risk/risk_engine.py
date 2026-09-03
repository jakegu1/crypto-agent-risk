"""
risk_engine.py
风险判定引擎 — 把原始链上/交易所数据加工成一个可执行的"风险画像"。

这是产品的核心价值：不是给 agent 一堆数字，而是给它一个**能直接用于决策**的结论。

信号来源：
- 流动性深度 (DexScreener/GeckoTerminal)
- Honeypot / 合约安全问题 (honeypot.is)
- 池子新鲜度 (new pools)
- 流动性集中度 / 持有人集中度 (间接)
- 多链存在性 (跨链合规性信号)

输出统一 schema：
{
  "address": str,
  "risk_level": "low"|"medium"|"high"|"unknown",
  "risk_score": int,          # 0-100 (越高越危险)
  "signals": [ {"name", "severity", "message"} ],
  "recommendation": str,      # 一句话给 agent 的建议
  "evidence": { ...原始证据快照 }
}
"""

from __future__ import annotations
from typing import Any

from . import data_sources as ds


def _severity(level: str) -> int:
    return {"ok": 0, "info": 10, "warn": 30, "critical": 55, "fatal": 80}.get(level, 10)


async def assess_token_risk(address: str, chain_hint: str | None = None) -> dict:
    """核心入口：给出一个代币的风险画像。

    address 可以是合约地址（ERC-20/SOL），也可以是一个交易对地址。
    chain_hint 用于提示主链（solana/ethereum/base/bsc 等），不传则自动探测多链。
    """
    address = (address or "").strip()
    if not address:
        return _empty_result(address, "缺少地址")

    signals: list[dict] = []
    evidence: dict[str, Any] = {}

    # --- 1. 多链流动性 / 交易对 ---
    token_pairs_raw = await ds.dexscreener_token(address)
    token_pairs = token_pairs_raw.get("pairs", [])
    if token_pairs:
        # 深度最好的交易对作为主参考
        best = max(token_pairs, key=lambda p: _fdv_or_zero(p))
        evidence["best_pair"] = {
            "dex": best.get("dexId"),
            "chain": best.get("chainId"),
            "liquidity_usd": _fdv_or_zero(best),
            "price_usd": best.get("priceUsd"),
            "volume_24h_usd": _num(best.get("volume", {}).get("h24")),
            "fc_24h": _num(best.get("priceChange", {}).get("h24")),
            "pair_created_at": best.get("pairCreatedAt"),
        }
        liq_usd = _fdv_or_zero(best)
        if liq_usd < 5000:
            signals.append(_sig("critical", "流动性极低", f"主交易对流动性仅 ${liq_usd:,.0f}，rug/滑点风险极高", "liquidity"))
        elif liq_usd < 50000:
            signals.append(_sig("warn", "流动性偏弱", f"主交易对流动性 ${liq_usd:,.0f}", "liquidity"))
        else:
            signals.append(_sig("ok", "流动性充足", f"主交易对流动性 ${liq_usd:,.0f}", "liquidity"))

        # 跨链存在性 (多链=更合规，单链新币=风险)
        chains = {p.get("chainId") for p in token_pairs}
        evidence["chains"] = sorted(c for c in chains if c)
        if len(chains) <= 1:
            signals.append(_sig("warn", "单链代币", "仅存在于单个链，流动性难跨链验证", "cross_chain"))
        else:
            signals.append(_sig("ok", "多链流通", f"见于 {len(chains)} 条链", "cross_chain"))
    else:
        # 区分"真的没流动性"与"数据没拿到"：若是源调用失败则标记为数据缺失，不作风险判定
        if token_pairs_raw.get("_source_error"):
            evidence["liquidity_source"] = "error"
            signals.append(_sig("info", "流动性数据缺失", "上游数据源暂时不可用，未能核实流动性", "source_error"))
        else:
            signals.append(_sig("warn", "未找到流动性", "DexScreener 未检索到该地址的交易对", "no_liquidity"))

    # --- 2. Honeypot 检查 (主要针对 EVM 合约) ---
    if _looks_evm(address):
        hp = await ds.honeypot_check(address)
        evidence["honeypot"] = hp
        summary = hp.get("simulationResult", {})
        is_hp = summary.get("isHoneypot", False)
        if is_hp:
            signals.append(_sig("fatal", "Honeypot 检测", "仿真检测出 honeypot：只能买不能卖需警惕", "honeypot"))
        else:
            # 检查买卖税 → 高税是潜在的 rug 前兆
            buy_tax = _num(summary.get("buyTax"))
            sell_tax = _num(summary.get("sellTax"))
            if sell_tax and sell_tax > 20:
                signals.append(_sig("critical", "高卖方税", f"卖出税 {sell_tax:.0f}%，可能无法正常卖出", "sell_tax"))
            else:
                signals.append(_sig("ok", "非 Honeypot", "未检测到 honeypot 特征", "honeypot"))

    # --- 3. 池子新鲜度 / 新币风险 ---
    # 主交易对创建时间越近，rug 风险越高
    created = evidence.get("best_pair", {}).get("pair_created_at")
    if created:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - dt).days
            evidence["pair_age_days"] = age_days
            if age_days < 3:
                signals.append(_sig("critical", "极新交易对", f"主交易对仅 {age_days} 天，rug/跑路高发期", "freshness"))
            elif age_days < 30:
                signals.append(_sig("warn", "较新交易对", f"主交易对 {age_days} 天", "freshness"))
            else:
                signals.append(_sig("ok", "成熟交易对", f"交易对已存在 {age_days} 天", "freshness"))
        except Exception:  # noqa: BLE001
            pass

    # --- 4. 持有人 / 集中度 (从 DexScreener 不直接可得，留空标记) ---
    evidence["holder_concentration"] = "not_available"  # 说明：DexScreener 不直接给持有人分布，后续可扩展

    # --- 5. 最后汇总评分 ---
    return _finalize(address, signals, evidence)


async def get_token_liquidity(address: str) -> dict:
    """流动性快照：给 agent 判断深度用的原始+加工数据。"""
    address = (address or "").strip()
    token_pairs = (await ds.dexscreener_token(address)).get("pairs", [])
    if not token_pairs:
        return {"address": address, "liquidity_usd": 0, "pairs": [],
                "note": "DexScreener 未检索到交易对"}
    best = max(token_pairs, key=lambda p: _fdv_or_zero(p))
    return {
        "address": address,
        "best_pair_chain": best.get("chainId"),
        "best_pair_dex": best.get("dexId"),
        "price_usd": best.get("priceUsd"),
        "liquidity_usd": _fdv_or_zero(best),
        "volume_24h_usd": _num(best.get("volume", {}).get("h24")),
        "price_change_24h_pct": _num(best.get("priceChange", {}).get("h24")),
        "pairs_total": len(token_pairs),
        "chains": sorted({p.get("chainId") for p in token_pairs if p.get("chainId")}),
    }


async def find_new_hot_pools(chain: str = "solana", limit: int = 10) -> list[dict]:
    """某链最新/最热的新池（供 agent 扫描新币机会 + 评估风险）。"""
    new_pools = (await ds.geckoterminal_new_pools(chain)).get("data", [])
    trending = await ds.geckoterminal_trending_pools(chain)
    merged: dict[str, dict] = {}
    for p in new_pools:
        pid = p.get("id")
        if pid:
            merged[pid] = _pool_summary(p, kind="new")
    for p in trending:
        pid = p.get("id")
        if pid and pid not in merged:
            merged[pid] = _pool_summary(p, kind="trending")
    return list(merged.values())[:limit]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _sig(severity: str, name: str, message: str, category: str) -> dict:
    return {"severity": severity, "name": name, "message": message, "category": category}


def _fdv_or_zero(pair: dict) -> float:
    """取流动性 FDV/流动性指标。DexScreener 用 liquidity.usd，Gecko 用 reserve_in_usd。"""
    liq = pair.get("liquidity") or {}
    v = liq.get("usd", 0)
    if not v:
        # 后备：用 reserve 估值
        v = pair.get("reserveInUsd") or pair.get("fdv") or 0
    return _num(v)


def _num(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _looks_evm(address: str) -> bool:
    """粗略判断是否为 EVM 合约地址（0x + 40 hex）。"""
    return len(address) == 42 and address.startswith("0x")


def _pool_summary(p: dict, kind: str) -> dict:
    attrs = p.get("attributes", {})
    return {
        "kind": kind,
        "pool_id": p.get("id"),
        "name": attrs.get("name"),
        "price_usd": attrs.get("base_token_price_usd"),
        "price_change_24h_pct": attrs.get("price_change_percentage", {}).get("h24"),
        "volume_24h_usd": attrs.get("volume_usd", {}).get("h24"),
        "liquidity_usd": attrs.get("reserve_in_usd"),
        "txns_24h": attrs.get("transactions", {}).get("h24"),
    }


def _finalize(address: str, signals: list[dict], evidence: dict) -> dict:
    """汇总评分：severity 权重 → risk_score (0-100)。"""
    score = min(100, sum(_severity(s["severity"]) for s in signals))
    # 有真实正向信号时不要判 unknown
    has_positive = any(s["severity"] in ("ok", "info") for s in signals)
    if not signals and not has_positive:
        level = "unknown"
    elif score >= 55:
        level = "high"
    elif score >= 25:
        level = "medium"
    elif has_positive:
        level = "low"
    else:
        level = "unknown"

    critical = [s for s in signals if s["severity"] in ("critical", "fatal")]
    if level == "high" and not critical:
        level = "medium"  # 无致命信号时不要轻易标高

    rec = _recommendation(level, signals)
    return {
        "address": address,
        "risk_level": level,
        "risk_score": score,
        "signals": signals,
        "recommendation": rec,
        "evidence": evidence,
    }


def _recommendation(level: str, signals: list[dict]) -> str:
    if level == "high":
        return "高风险：不建议在没有深入审核的情况下大额买入。先核实合约/持有/审计。"
    if level == "medium":
        return "中等风险：可小额试探，但务必控制仓位、设置止损。关注流动性退出与新池老化。"
    if level == "low":
        return "低风险：流动性充足且无 honeypot/高税信号，可正常评估。"
    return "信息不足以判定，建议二次核实合约与流动性。"


def _empty_result(address: str, reason: str) -> dict:
    return {
        "address": address,
        "risk_level": "unknown",
        "risk_score": 0,
        "signals": [_sig("warn", "输入无效", reason, "input")],
        "recommendation": "无法评估，请重新检查地址是否为合约/交易对地址。",
        "evidence": {},
    }
