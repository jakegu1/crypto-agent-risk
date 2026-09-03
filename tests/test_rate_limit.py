"""rate_limit 单元测试 — 验证防刷逻辑（不依赖网络）。"""
import pytest

from crypto_agent_risk import rate_limit as rl


@pytest.fixture(autouse=True)
def _reset_state():
    rl._ip_buckets.clear()
    rl._global_calls.clear()
    yield


def test_health_path_free():
    # 健康/文档/mcp 路径不受限流，即使高频
    for _ in range(300):
        assert rl.is_allowed("1.1.1.1", "/health") is True


def test_rate_limits_same_ip():
    # 同一 IP 超过 60/min + 30 突发时开始拒绝
    allowed = sum(1 for _ in range(200) if rl.is_allowed("2.2.2.2", "/assess/0x"))
    assert 0 <= allowed <= rl.IP_RATE_LIMIT + rl.IP_BURST


def test_global_limit():
    # 全局上限确实是硬闸门
    total = 0
    for _ in range(rl.GLOBAL_RATE_LIMIT + 50):
        if rl.is_allowed(f"ip-{_}", "/new-pools"):
            total += 1
        else:
            break
    assert total <= rl.GLOBAL_RATE_LIMIT + 1


def test_client_ip_uses_forwarded_header():
    class FakeReq:
        headers = {"x-forwarded-for": "203.0.113.5, 10.0.0.1"}
        client = None
    assert rl.client_ip(FakeReq()) == "203.0.113.5"
