# Oracle-X MCP Server

Exposes a running Oracle-X instance to any MCP client as 36 tools — prices,
technical zones, news analysis, macro regime, chain metrics, liquidations,
ownership, and the vector memory.

## Why this exists next to the agent skill

`agent-skill/oracle-x-api` documents the same API, and it is well written. It
also measured **0% trigger recall**: across twenty realistic queries and three
rewrites of its description, a model essentially never chose to consult it. A
skill has to be looked up, and a model asked "what is BTC doing" answers from
its own knowledge instead.

Tools do not have that problem. They are already in the model's context, so the
only decision left is which one to call. Same data, different failure mode.

Keep both: the skill teaches an agent to script against the HTTP API, which is
what you want when writing code. The MCP server is what you want when you are
asking questions.

## Install

```bash
cd mcp-server
python3.11 -m venv .venv          # 3.10+; the MCP SDK requires it
.venv/bin/pip install -e .
```

Register it with your client. For Claude Code:

```bash
claude mcp add oracle-x -e ORACLE_X_URL=http://localhost:8000 \
  -- /absolute/path/to/mcp-server/.venv/bin/python -m oracle_x_mcp
```

Or in an MCP client's JSON configuration:

```json
{
  "mcpServers": {
    "oracle-x": {
      "command": "/absolute/path/to/mcp-server/.venv/bin/python",
      "args": ["-m", "oracle_x_mcp"],
      "env": {
        "ORACLE_X_URL": "http://localhost:8000",
        "ORACLE_X_TOKEN": "optional-supabase-access-token"
      }
    }
  }
}
```

`ORACLE_X_TOKEN` is needed only by `ask_oracle` and `get_watchlist`. Everything
else is open on a default instance.

## The tools

| Group | Tools |
|---|---|
| Instance | `check_instance` |
| Prices and levels | `get_price`, `get_technical_levels`, `get_candles`, `get_asset_fundamentals`, `get_market_overview`, `get_market_indices` |
| News | `list_news`, `get_news_analysis`, `find_similar_news` |
| Reports and macro | `get_analysis_report`, `get_macro_regime`, `get_macro_board` |
| Chains | `get_chains_board`, `get_chain_anomalies` |
| Flow | `get_liquidation_map`, `get_funding_rates`, `get_whale_flow`, `get_ownership`, `get_ownership_moves` |
| Memory | `search_memory`, `get_symbol_history`, `compare_assets`, `get_daily_brief` |
| Oracle | `ask_oracle`, `get_watchlist` |
| Prediction markets | `get_prediction_markets`, `get_prediction_market`, `analyse_prediction_market`, `get_prediction_analysis_job` |

Thirty, not a hundred and fifty. A tool list is context every turn pays
for, so the routes that exist for the UI to talk to itself are not here.

## Two things the tools do that a thin proxy would not

**Failures arrive as data, never as exceptions.** Every tool returns
`{"ok": false, "reason": "..."}` rather than raising. A raised error gives the
model a stack trace and an invitation to retry, and none of these conditions
improve on a retry: an unresolvable symbol stays unresolvable, a missing token
stays missing, a stopped instance stays stopped. Each reason says which of the
three it is.

**Payloads are summarized where the raw one is a rendering artifact.**
`/api/liquidations/map/` answers with about 8,000 heatmap cells and a candle
series — 214 KB, roughly 55k tokens. The tool returns the largest clusters per
side anchored to spot: 1.1 KB carrying the same information. Zero-notional bins
are dropped rather than ranked, and an empty side is stated explicitly, because
"nothing is stacked above spot" is a finding and an omitted key reads like a
lookup that never happened. `get_chains_board` drops the per-chain block list
that feeds a UI sparkline.

## Development

```bash
cd mcp-server
.venv/bin/python -m pytest        # 19 tests
.venv/bin/ruff check . --exclude .venv
.venv/bin/ruff format --check . --exclude .venv
```

The tests assert the *shape* of results — that a decline is distinguishable
from an outage, that a summary never invents a cluster — rather than that a
request was made. Upstreams are stubbed at `server.client`, matching the
backend suite's convention of patching the import site rather than httpx.
