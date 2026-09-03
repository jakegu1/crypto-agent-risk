"""
server.py
FastMCP 工具暴露层 — 把风险引擎包装成 AI 代理可直接调用的工具。

暴露给 MCP client 的工具：
  1. assess_token_risk(address, chain_hint?)  -> 核心风险画像
  2. get_token_liquidity(address)             -> 流动性快照
  3. find_new_hot_pools(chain?, limit?)       -> 新池/热门扫描

同时挂 FastAPI，提供 HTTP 端点（供后续 x402 托管 + 健康检查 + 监控）。
"""

from __future__ import annotations
import logging

from fastmcp import FastMCP

from . import data_sources as ds
from . import risk_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("crypto-agent-risk.server")

# --- FastMCP server (MCP 工具接口) ---
mcp = FastMCP(
    name="crypto-agent-risk",
    instructions=(
        "代币风险情报工具。给 AI 代理用的：在持有/买入/调研一个代币前，先用它评估风险。"
        "assess_token_risk 返回结构化风险画像(level/score/signals/recommendation)；"
        "get_token_liquidity 返回流动性快照；find_new_hot_pools 扫描新池。"
        "注意：这是情报辅助，不构成投资建议。"
    ),
    version="0.1.0",
)


@mcp.tool(name="assess_token_risk", title="评估代币风险画像",
          description="聚合多链流动性/合约安全/新鲜度，输出一个可执行的风险结论(low/medium/high)和给agent的建议。address应为ERC-20或Solana合约地址。")
async def assess_token_risk(address: str, chain_hint: str | None = None) -> dict:
    """评估一个代币的综合风险，供决策参考。"""
    return await risk_engine.assess_token_risk(address, chain_hint)


@mcp.tool(name="get_token_liquidity", title="查代币流动性快照",
          description="返回某代币的主交易对流动性、价格、24h量、跨链数。供判断交易深度。")
async def get_token_liquidity(address: str) -> dict:
    """获取代币流动性快照。"""
    return await risk_engine.get_token_liquidity(address)


@mcp.tool(name="find_new_hot_pools", title="扫描新池/热门池",
          description="扫描某链(默认solana)最新创建或最热的新交易池，返回价格/流动性/交易量概览。用于发现新币与评估其风险。")
async def find_new_hot_pools(chain: str = "solana", limit: int = 10) -> list[dict]:
    """扫描某链的新池/热门池。"""
    return await risk_engine.find_new_hot_pools(chain, limit)


# --- ASGI app: 远程 MCP transport (streamable-http) 作为主 app ---
# 对外: /cryptorisk/mcp  (经 nginx 剥离前缀后到本服务的 /mcp)
# MCP 端点 /mcp 由 FastMCP 直接处理，不嵌套 mount，避免路径双重拼接/尾斜杠404
app = mcp.http_app(transport="streamable-http")
mcp_path = "/mcp"


# 辅助 HTTP 端点 (为 x402 托管 + 监控预留)。直接作为独立路由挂在主 app 上。
from starlette.responses import JSONResponse, HTMLResponse
import json
import os

from . import rate_limit

_LANDING_PATH = os.path.join(os.path.dirname(__file__), "landing.html")


async def landing(req) -> HTMLResponse:
    """落地页：给开发者看 + 给 AI 引擎读（GEO）。"""
    try:
        with open(_LANDING_PATH, "r", encoding="utf-8") as f:
            html = f.read()
        return HTMLResponse(html)
    except FileNotFoundError:
        return HTMLResponse("<h1>Crypto Agent Risk</h1><p>Landing page not found.</p>", status_code=500)


async def _json(data) -> JSONResponse:
    return JSONResponse(data)


async def health(req) -> JSONResponse:
    """健康检查（放行，不限流）。"""
    return JSONResponse({"status": "ok", "service": "crypto-agent-risk", "mcp_tools": 3})


async def assess_http(req) -> JSONResponse:
    """HTTP 直调版评估。"""
    address = req.path_params.get("address", "")
    chain_hint = req.query_params.get("chain_hint")
    r = await risk_engine.assess_token_risk(address, chain_hint)
    return JSONResponse(r)


async def liquidity_http(req) -> JSONResponse:
    """HTTP 直调版流动性。"""
    address = req.path_params.get("address", "")
    r = await risk_engine.get_token_liquidity(address)
    return JSONResponse(r)


async def new_pools_http(req) -> JSONResponse:
    """HTTP 直调版新池。"""
    chain = req.query_params.get("chain", "solana")
    limit = int(req.query_params.get("limit", "10"))
    r = await risk_engine.find_new_hot_pools(chain, limit)
    return JSONResponse(r)


def _wrapped(handler):
    """用限流+日志包装一个端点 handler。"""
    async def wrapper(req):
        return await rate_limit.call_tool_handler(handler, req)
    wrapper.__name__ = getattr(handler, "__name__", "handler")
    return wrapper


app.add_route("/health", health, methods=["GET"])
app.add_route("/", landing, methods=["GET"])
app.add_route("/assess/{address}", _wrapped(assess_http), methods=["GET"])
app.add_route("/liquidity/{address}", _wrapped(liquidity_http), methods=["GET"])
app.add_route("/new-pools", _wrapped(new_pools_http), methods=["GET"])


# 供 `uvicorn crypto_agent_risk.server:app` 直接跑 HTTP (app 已是完整 ASGI)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8123)
