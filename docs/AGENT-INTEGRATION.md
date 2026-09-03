# 🛡️ Crypto Agent Risk — 代币风险情报 MCP

给 **AI 代理** 用的代币风险评估工具。在代理持有 / 买入 / 调研一个代币前，先让它评估风险，直接拿到**可执行的判断**（`low` / `medium` / `high`），而不是一堆需要二次解读的数字。

> ⚠️ 情报辅助工具，**不构成投资建议**。

## 🌐 接入方式（远程 MCP，无需本地安装）

这个 server 通过 **MCP over HTTP**（streamable-http transport）远程暴露，agent 只需一个 URL 即可连接，**不需要 clone / 安装 / 本地跑任何东西**。

```
MCP 端点:  https://vetagent.dev/mcp
Transport: streamable-http
```

### Claude Desktop / Claude Code 接入
在你的 `claude_desktop_config.json` 增加：

```json
{
  "mcpServers": {
    "crypto-agent-risk": {
      "type": "http",
      "url": "https://vetagent.dev/mcp"
    }
  }
}
```

### 任意 MCP 客户端（Cursor / opencode / 自定义）
大多数 MCP 客户端支持远程 HTTP server。配置一个指向上述 URL 的 `http` transport 连接即可。

> 注：当前为 IP 直连（HTTP）。后续该服务可通过域名 + HTTPS 升级，只需改 URL，功能不变。

## 🧰 提供的工具

### 1. `assess_token_risk(address, chain_hint?)` — 核心评估
评估一个代币的综合风险，返回**结构化画像**：
```json
{
  "address": "0x7D1...",
  "risk_level": "low",
  "risk_score": 0,
  "signals": [
    {"severity": "ok", "name": "流动性充足", "message": "...", "category": "liquidity"},
    {"severity": "ok", "name": "多链流通", "message": "...", "category": "cross_chain"},
    {"severity": "ok", "name": "非 Honeypot", "message": "...", "category": "honeypot"}
  ],
  "recommendation": "低风险：流动性充足且无 honeypot/高税信号，可正常评估。",
  "evidence": { "...": "原始证据快照" }
}
```
- `risk_level`: `low` / `medium` / `high` / `unknown`
- `signals`: 逐条风险信号（severity: ok/info/warn/critical/fatal）
- `recommendation`: **给 agent 的一句话决策建议**（可直接用于后续判断）
- 聚合信号来源：多链流动性深度、跨链存在性、Honeypot 检测、池子新鲜度

### 2. `get_token_liquidity(address)` — 流动性快照
```json
{
  "best_pair_chain": "ethereum",
  "best_pair_dex": "uniswap",
  "price_usd": "...",
  "liquidity_usd": 107334931.08,
  "volume_24h_usd": "...",
  "price_change_24h_pct": "...",
  "pairs_total": 30,
  "chains": ["ethereum", "pulsechain"]
}
```

### 3. `find_new_hot_pools(chain, limit)` — 新池扫描
扫描某链最新创建 / 最热的新交易池（用于发现新币 + 评估风险），返回价格 / 流动性 / 交易量概览。

## 📊 数据来源（全部免费、实时、免密）
| 数据源 | 覆盖 |
|---|---|
| DexScreener | 多链 meme/新币/价格/流动性/token-profile |
| GeckoTerminal | 池子/流动性/链上行情 |
| honeypot.is | Ethereum 合约反诈骗（Honeypot 检测） |
| CoinGecko | 全量币价/市值/涨跌 |

## 🔌 HTTP 端点（不使用 MCP 亦可直调）
```
GET /cryptorisk/health
GET /cryptorisk/assess/{address}?chain_hint=
GET /cryptorisk/liquidity/{address}
GET /cryptorisk/new-pools?chain=solana&limit=10
```

## 🎯 典型使用场景（给代理的提示词范例）
> "帮我评估一下代币 0x7D1... 的风险，如果低于 medium 我才考虑建仓。"
> "扫一下 Solana 最新 5 个新池，列出可能有 rug 风险的。"
> "查一下 0xC02... 的流动性深度，判断滑点风险。"

## 🔒 诚实的边界
- **免费公开服务**，当前无鉴权、无计费（后续可选接 x402 按次付费）
- 数据为**公开链上/交易所数据**，不构成金融建议
- 单点签名：Honeypot 检测仅覆盖 EVM；流动性数据来自 DexScreener/GeckoTerminal，**非真实资金规模**
