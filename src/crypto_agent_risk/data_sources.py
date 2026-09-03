"""
data_sources.py
数据源聚合层 — 封装对免费、实时的加密数据 API 的访问。

设计原则：
- 每个数据源一个函数，返回标准化 dict，不抛异常（失败时给空结果 + 错误标记）
- 内置 TTL 缓存，避免撞上游限流/延迟
- 单一 httpx.Client 池复用连接
- 所有请求真实、可溯源，绝不伪造数据
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("crypto-agent-risk.data")

# 全局连接池 + 简易 TTL 缓存
_client: httpx.AsyncClient | None = None
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 30  # 秒


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={"Accept": "application/json"},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True,
        )
    return _client


async def _cached(key: str, fetcher, ttl: int = _CACHE_TTL) -> Any:
    """TTL 缓存包装：命中直接返回，未命中执行 fetcher。"""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        result = await fetcher()
    except Exception as exc:  # noqa: BLE001 — 池层吞异常，返回空
        logger.warning("fetch %s failed: %s", key, exc)
        return {}
    if result:  # 只在拿到非空结果时写缓存
        _cache[key] = (now, result)
    return result


async def _get_json(url: str, params: dict | None = None, retries: int = 2) -> Any:
    """GET 一个 JSON 端点，失败返回 None。带指数退避重试，容忍 TLS/wobble。"""
    import asyncio
    for attempt in range(retries + 1):
        try:
            client = await _get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GET %s failed (attempt %d/%d): %s", url, attempt + 1, retries + 1, exc)
            if attempt < retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
    return None


# ---------------------------------------------------------------------------
# DexScreener — 多链 meme / 新币 / 流动性 / token-profile(风险+社交)
# ---------------------------------------------------------------------------
async def dexscreener_search(query: str) -> dict:
    """按名称/符号/地址搜索交易对。返回标准化 {pairs: [...]}"""
    data = await _cached(f"ds_search:{query}", lambda: _get_json(
        "https://api.dexscreener.com/latest/dex/search", {"q": query}))
    if not data:
        return {}
    return {"pairs": data.get("pairs", [])}


async def dexscreener_token(address: str) -> dict:
    """按 token 合约地址查全链深度。返回 {pairs: [...]}
    注意：DexScreener 的 /tokens 端点是路径式 /tokens/{address}，用 f-string 插值。
    若源完全不可用，返回 {"_source_error": True} 供上层区分'数据缺失'与'真没数据'。"""
    raw = await _cached(f"ds_token:{address}", lambda: _get_json(
        f"https://api.dexscreener.com/latest/dex/tokens/{address}"))
    if raw is None:
        return {"pairs": [], "_source_error": True}
    data = raw if isinstance(raw, dict) else {}
    return {"pairs": data.get("pairs", [])}


async def dexscreener_pair(pair_address: str) -> dict:
    """按交易对地址查询。"""
    data = await _cached(f"ds_pair:{pair_address}", lambda: _get_json(
        "https://api.dexscreener.com/latest/dex/pairs/{pair}"))
    if not data:
        return {}
    return {"pairs": data.get("pairs", [])}


async def dexscreener_token_profiles() -> list[dict]:
    """最新 token-profile（含社交/风险信号）。"""
    data = await _cached("ds_profiles", lambda: _get_json(
        "https://api.dexscreener.com/token-profiles/latest/v1"))
    if not isinstance(data, list):
        return []
    return data


async def dexscreener_boosted_tokens() -> list[dict]:
    """被 boost 的热门 token（付费推广 + 社交热度信号）。"""
    data = await _cached("ds_boosted", lambda: _get_json(
        "https://api.dexscreener.com/token-boosts/latest/v1"))
    if not isinstance(data, list):
        return []
    return data


# ---------------------------------------------------------------------------
# GeckoTerminal — 池子 / 流动性 / 链上行情 / 新池
# ---------------------------------------------------------------------------
async def geckoterminal_new_pools(chain: str = "solana") -> dict:
    """某链最新创建的新池（追踪新币/rug 风险的重要信号）。"""
    data = await _cached(f"gt_new_pools:{chain}", lambda: _get_json(
        f"https://api.geckoterminal.com/api/v2/networks/{chain}/new_pools"))
    if not data:
        return {}
    return {"data": data.get("data", []), "included": data.get("included", [])}


async def geckoterminal_trending_pools(chain: str = "solana") -> list[dict]:
    """某链 trending 池（热度信号）。"""
    data = await _cached(f"gt_trending:{chain}", lambda: _get_json(
        f"https://api.geckoterminal.com/api/v2/networks/{chain}/trending_pools"))
    if not data:
        return []
    return data.get("data", [])


async def geckoterminal_pool(pool_id: str) -> dict:
    """单个池子详情（深度 OHLCV 结构）。"""
    data = await _cached(f"gt_pool:{pool_id}", lambda: _get_json(
        f"https://api.geckoterminal.com/api/v2/networks/pools/{pool_id}"))
    if not data:
        return {}
    return data.get("data", {})


# ---------------------------------------------------------------------------
# honeypot.is — ETH 合约一键反诈骗（Honeypot 检测）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# RugCheck (Solana) — 代币风险评分 / rug 检测
# ---------------------------------------------------------------------------
async def rugcheck_report(mint: str) -> dict:
    """Solana 代币的 rug 检测报告（含分数 + 风险条目）。mint 为代币地址。"""
    data = await _cached(f"rc:{mint}", lambda: _get_json(
        f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"), ttl=300)
    if not isinstance(data, dict):
        return {}
    return data


async def honeypot_check(address: str) -> dict:
    """检测 ERC-20 是否 honeypot。address 为合约地址。"""
    data = await _cached(f"hp:{address}", lambda: _get_json(
        f"https://api.honeypot.is/v2/IsHoneypot", {"address": address}), ttl=300)
    if not data:
        return {}
    return data


# ---------------------------------------------------------------------------
# CoinGecko — 全量币价 / 市值 / 涨跌 / 元数据
# ---------------------------------------------------------------------------
async def coingecko_meta(coin_id: str) -> dict:
    """单个币的元数据（描述/官网/社交/分类）。"""
    data = await _cached(f"cg_meta:{coin_id}", lambda: _get_json(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}"), ttl=3600)
    if not data:
        return {}
    return data


async def coingecko_prices(symbols: str) -> dict:
    """多个代币简单价格（USD + 24h 涨跌）。symbols: 'bitcoin,trx'"""
    data = await _cached(f"cg_price:{symbols}", lambda: _get_json(
        "https://api.coingecko.com/api/v3/simple/price",
        {"ids": symbols, "vs_currencies": "usd", "include_24hr_change": "true"}))
    if not data:
        return {}
    return data


async def close() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
