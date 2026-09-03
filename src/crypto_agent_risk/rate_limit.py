"""
rate_limit.py
轻量进程内限流 + 访问日志。

这是公开暴露产品的一道必要防线：防止免费服务被刷爆/滥用。
- IP 令牌桶：默认每 IP 每分钟 <=60 次，突发 <=30
- 全局滑动窗口：防止整体被打爆
- 记录每次调用到 JSONL（调用量监控的种子数据）

注意：单进程 uvicorn 下足够。若未来多 worker/多实例，需换 Redis 分布式限流。
"""
from __future__ import annotations
import json
import os
import time
from collections import defaultdict, deque
from typing import Any

from starlette.responses import JSONResponse

# 配置
IP_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))       # 每IP每分钟
IP_BURST = int(os.getenv("RATE_LIMIT_BURST", "30"))             # 突发窗口
GLOBAL_RATE_LIMIT = int(os.getenv("GLOBAL_RATE_LIMIT_PER_MIN", "2400"))  # 全局每分钟
LOG_PATH = os.getenv("ACCESS_LOG", "/home/ubuntu/projects/crypto-agent-risk/access.jsonl")

# 状态
_ip_buckets: dict[str, deque[float]] = defaultdict(deque)
_global_calls: deque[float] = deque()
_GLOBAL_WINDOW = 60.0

# 保护不拦截的路径（健康检查/文档等低价值路径）
FREE_PATHS = ("/health", "/docs", "/openapi", "/mcp/")


def _now() -> float:
    return time.time()


def _prune(dq: deque[float], window: float, now: float) -> None:
    while dq and now - dq[0] > window:
        dq.popleft()


def is_allowed(client_ip: str, path: str) -> bool:
    """返回是否允许该请求。健康/文档路径放行，其余走限流。"""
    if any(path.startswith(p) or p.rstrip("/") in path for p in FREE_PATHS):
        return True
    now = _now()
    # 全局
    _prune(_global_calls, _GLOBAL_WINDOW, now)
    if len(_global_calls) >= GLOBAL_RATE_LIMIT:
        return False
    _global_calls.append(now)
    # 每 IP
    bucket = _ip_buckets[client_ip]
    _prune(bucket, _GLOBAL_WINDOW, now)
    if len(bucket) >= IP_RATE_LIMIT + IP_BURST:
        return False
    bucket.append(now)
    return True


async def log_call(path: str, client_ip: str, status: int, note: str = "") -> None:
    """记录一次调用（append-only JSONL）。"""
    try:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ip": client_ip,
            "path": path,
            "status": status,
            "note": note,
        }
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 日志失败不影响主流程
        pass


def client_ip(request) -> str:
    """从请求拿客户端 IP（优先 X-Forwarded-For，因为走 nginx 反代）。"""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def call_tool_handler(handler, request) -> JSONResponse:
    """包装一个端点：限流 + 日志。不通过则返回 429。"""
    ip = client_ip(request)
    path = request.url.path
    if not is_allowed(ip, path):
        await log_call(path, ip, 429, "rate_limited")
        return JSONResponse({"detail": "Too Many Requests"}, status_code=429)
    result = await handler(request)
    await log_call(path, ip, 200)
    return result
