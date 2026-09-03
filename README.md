# Crypto Agent Risk

给 AI 代理用的**代币风险情报** MCP server。在持有/买入/调研一个代币前，让代理先评估风险，直接拿到**可执行的判断**（low/medium/high），而不是一堆数字。

## 为什么做这个
- 数据源全部免费、实时、免密（DexScreener / GeckoTerminal / honeypot.is / CoinGecko）
- 把"数据查询"升级为"决策情报"：聚合多链流动性 + 合约安全 + 池子新鲜度 → 结构化风险画像
- 面向 AI 代理的信任/风险层（对标 a16z 说的 agent 最大缺口 = 信任/治理）

## 工具
| 工具 | 作用 |
|---|---|
| `assess_token_risk(address, chain_hint?)` | 核心：聚合风险，输出 level/score/signals/recommendation |
| `get_token_liquidity(address)` | 流动性快照（价格/24h量/跨链数） |
| `find_new_hot_pools(chain, limit)` | 扫描某链新池/热门池 |

## 运行
```bash
# MCP (stdio)
uv run python -c "from crypto_agent_risk.server import mcp; mcp.run()"

# HTTP
uv run uvicorn crypto_agent_risk.server:app --host 0.0.0.0 --port 8123
```

## 端点
- `GET /health`
- `GET /assess/{address}`
- `GET /liquidity/{address}`
- `GET /new-pools?chain=solana&limit=10`

## 架构
```
src/crypto_agent_risk/
  data_sources.py   # 免费数据源聚合 (TTL缓存/重试/容错)
  risk_engine.py    # 风险判定引擎 (信号评分→结构化画像)
  server.py         # FastMCP 工具 + FastAPI HTTP
```

## 验证
- MATIC / ETH Wrapped → `low`（流动性充足/多链/非honeypot）
- 死地址 → 无流动性警告
- Solana 新池扫描 → 实时新池
