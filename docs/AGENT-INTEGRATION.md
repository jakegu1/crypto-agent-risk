# 🤖 VetAgent — AI Agent Integration Guide

VetAgent is a **token risk intelligence MCP server** for AI agents. Before an agent buys, holds, or researches a crypto token, it can call VetAgent to get an **actionable risk verdict** (`low` / `medium` / `high`) — not a pile of numbers to re-interpret.

> ⚠️ Intelligence aid only. **Not investment advice.** Data comes from public on-chain/exchange sources. Liquidity figures are indicative (not true TAM of capital); honeypot check covers EVM only.

---

## 🔌 Remote MCP Endpoint (no local install)

Connect directly over MCP-over-HTTP to the endpoint:

```
https://vetagent.dev/mcp
```

### Claude Desktop / Claude Code config
Add to your `claude_desktop_config.json` (or MCP config):
```json
{
  "mcpServers": {
    "vetagent": {
      "type": "http",
      "url": "https://vetagent.dev/mcp"
    }
  }
}
```

Any MCP client (Cursor, opencode, custom agent) works the same way.

---

## 🧰 Tools (3)

| Tool | What it does |
|---|---|
| **`assess_token_risk(address, chain_hint?)`** | Core. Aggregates multi-chain liquidity / contract safety (honeypot or rug check) / pool freshness into a structured risk verdict + agent recommendation. |
| **`get_token_liquidity(address)`** | Best-pair liquidity snapshot: price, 24h volume, cross-chain count. |
| **`find_new_hot_pools(chain, limit)`** | Scan a chain (default `solana`) for newest/hottest new pools for new-token discovery + risk. |

### Example: `assess_token_risk`
```json
{
  "address": "0x7D1A...",
  "risk_level": "low",
  "risk_score": 0,
  "signals": [
    {"severity": "ok", "name": "流动性充足", "category": "liquidity"},
    {"severity": "ok", "name": "多链流通", "category": "cross_chain"},
    {"severity": "ok", "name": "非 Honeypot", "category": "honeypot"}
  ],
  "recommendation": "低风险：流动性充足且无 honeypot/高税信号，可正常评估。",
  "confidence": "medium"
}
```

**Routing guidance for an agent:** If `risk_level` is `high`, the agent should **warn the user and avoid** large unvetted buys. If `medium`, proceed cautiously with tight position sizing. If `low`, normal evaluation. `confidence` tells you how many independent signals were available.

---

## 🌐 HTTP API (also callable without MCP)

```
GET /health
GET /assess/{address}
GET /liquidity/{address}
GET /new-pools?chain=solana&limit=10
```

---

## 📊 Data Sources
| Source | Covers |
|---|---|
| DexScreener + GeckoTerminal (fallback) | Multi-chain meme/new tokens, price, liquidity, pools |
| honeypot.is | Ethereum contract anti-scam (buy/sell tax simulation) |
| RugCheck | Solana rug risk score |

The engine uses **source resilience**: if DexScreener is unavailable, GeckoTerminal is used as fallback for liquidity.

---

## 🎯 Example Agent Prompts
- *"Assess token 0x7D1A... for risk. If medium or above, hold off on position entry."*
- *"Scan the 5 newest Solana pools and flag any with rug risk."*
- *"Check liquidity depth of 0xC02... to estimate slippage risk."*

---

## 🔗 Links
- Live: **https://vetagent.dev**
- GitHub: [github.com/jakegu1/vetagent](https://github.com/jakegu1/vetagent)
