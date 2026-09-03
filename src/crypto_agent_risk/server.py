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

from fastapi import FastAPI
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


# --- FastAPI app (HTTP 端点 + 预留 x402) ---
app = FastAPI(title="Crypto Agent Risk API", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    """健康检查。"""
    return {"status": "ok", "service": "crypto-agent-risk", "mcp_tools": 3}


@app.get("/assess/{address}")
async def assess_http(address: str, chain_hint: str | None = None) -> dict:
    """HTTP 直调版评估（为 x402 托管预留的入口）。"""
    return await risk_engine.assess_token_risk(address, chain_hint)


@app.get("/liquidity/{address}")
async def liquidity_http(address: str) -> dict:
    """HTTP 直调版流动性。"""
    return await risk_engine.get_token_liquidity(address)


@app.get("/new-pools")
async def new_pools_http(chain: str = "solana", limit: int = 10) -> list[dict]:
    """HTTP 直调版新池。"""
    return await risk_engine.find_new_hot_pools(chain, limit)


# 供 `uvicorn crypto_agent_risk.server:app` 直接跑 HTTP
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8123)
