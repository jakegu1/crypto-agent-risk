"""risk_engine 的单元测试 — 核心评分/边界逻辑，不依赖网络。"""
import pytest

from crypto_agent_risk import risk_engine as re


# ---- helpers ----
def test__num():
    assert re._num("123.45") == 123.45
    assert re._num("abc") == 0.0
    assert re._num(None) == 0.0
    assert re._num("") == 0.0


def test__fdv_or_zero():
    assert re._fdv_or_zero({"liquidity": {"usd": 100}}) == 100
    assert re._fdv_or_zero({"reserveInUsd": 50}) == 50
    assert re._fdv_or_zero({}) == 0


def test__looks_evm():
    assert re._looks_evm("0x" + "a" * 40) is True
    assert re._looks_evm("0x" + "A" * 40) is True
    assert re._looks_evm("0x123") is False
    assert re._looks_evm("So11111111111111111111111111111111111111112") is False


def test__looks_solana():
    assert re._looks_solana("So11111111111111111111111111111111111111112") is True
    assert re._looks_solana("abc123") is False  # too short
    assert re._looks_solana("0x" + "a" * 40) is False
    assert re._looks_solana("00000000000000000000000000000000") is False  # contains 0 (not base58-safe, len 32 but has 0)


def test__severity():
    assert re._severity("fatal") >= re._severity("critical") >= re._severity("warn") >= re._severity("ok")


# ---- _finalize 评分 ----
def test_finalize_low_when_positive():
    signals = [re._sig("ok", "a", "m", "liquidity"),
               re._sig("ok", "b", "m", "cross_chain")]
    r = re._finalize("addr", signals, {})
    assert r["risk_level"] == "low"
    assert r["risk_score"] == 0
    assert r["confidence"] in ("medium", "high")


def test_finalize_high_when_critical():
    signals = [re._sig("critical", "a", "m", "liquidity"),
               re._sig("critical", "b", "m", "freshness")]
    r = re._finalize("addr", signals, {})
    assert r["risk_level"] == "high"
    assert r["risk_score"] >= 55


def test_finalize_combo_escalation():
    # 极低流动性(critical) + 新池(critical) -> 组合规则应标 high + 记录风险组合
    signals = [re._sig("critical", "流动性极低", "m", "liquidity"),
               re._sig("critical", "极新交易对", "m", "freshness")]
    r = re._finalize("addr", signals, {})
    assert r["risk_level"] == "high"
    assert "risk_combo" in r["evidence"]
    assert any("combo" in s["category"] for s in r["signals"])


def test_finalize_unknown_when_no_signals():
    r = re._finalize("addr", [], {})
    assert r["risk_level"] == "unknown"
    assert r["confidence"] == "low"


def test_finalize_confidence_high_with_definite():
    signals = [re._sig("ok", "a", "m", "liquidity"),
               re._sig("warn", "b", "m", "cross_chain"),
               re._sig("warn", "c", "m", "freshness")]
    r = re._finalize("addr", signals, {})
    assert r["confidence"] in ("medium", "high")


# ---- empty_result ----
def test_empty_result():
    r = re._empty_result("addr", "bad")
    assert r["risk_level"] == "unknown"
    assert r["signals"][0]["severity"] == "warn"


def test_recommendation_levels():
    assert "高风险" in re._recommendation("high", [])
    assert "低风险" in re._recommendation("low", [])
    assert "中等风险" in re._recommendation("medium", [])
