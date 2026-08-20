"""MCP tools over a running Oracle-X instance.

The agent skill in `agent-skill/oracle-x-api` documents the same API, and
measurement is why this exists alongside it: a skill has to be *consulted*, and
a model asked "what is BTC doing" will usually answer from its own knowledge
rather than go looking for one. Tools are different — they sit in the model's
context already, so the choice is only which tool to call.

That shapes what belongs here. Each tool is one question a person actually
asks, named for the question rather than for the route behind it, and the ~120
operations the terminal exposes are deliberately not all here. A tool list is
context every turn pays for.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer

from oracle_x_mcp import client
from oracle_x_mcp.client import NotFound, OracleXError

server = MCPServer(
    name="oracle-x",
    version="1.2.1",
    instructions=(
        "Tools for a self-hosted Oracle-X financial terminal. Every tool reads "
        "a live instance at $ORACLE_X_URL (default http://localhost:8000).\n\n"
        "Report what the instance returned and nothing else. When a tool says "
        "the instance has no data for a symbol, that is the answer — the "
        "backend deliberately refuses to emit a placeholder number, so "
        "supplying one from memory would contradict the user's own screen.\n\n"
        "Do not recompute what the terminal computed. get_technical_levels "
        "already builds support and resistance per timeframe and scores each "
        "zone by how many horizons confirm it; deriving your own levels from "
        "get_candles produces numbers that disagree with the terminal.\n\n"
        "Symbols carry their venue: crypto pairs are BTCUSDT or "
        "BINANCE:ETHUSDT, equities are the plain ticker (NVDA)."
    ),
)


def _fail(error: Exception) -> dict[str, Any]:
    """Turn an exception into a result the model can act on.

    Raising through the transport gives the model a stack trace and an
    invitation to retry. Every one of these conditions is either permanent for
    this input or fixable only by the user, so each comes back as data with the
    reason attached.
    """
    return {"ok": False, "reason": str(error)}


# ── Instance ────────────────────────────────────────────────────────────────


@server.tool()
async def check_instance() -> dict[str, Any]:
    """Check that the Oracle-X instance is reachable and which of its data
    sources are healthy.

    Call this first when any other tool reports no data, and before drawing a
    conclusion from an empty result. The health report is passive — it says
    what the last real call to each provider did — so a category reading
    `idle` means nobody has asked it yet, not that it is broken. Only a
    category reading `degraded` or `down` explains a missing payload.
    """
    try:
        health = await client.get("/api/system/health")
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, "url": client.base_url(), "health": health}


# ── Prices and levels ───────────────────────────────────────────────────────


@server.tool()
async def get_price(symbol: str) -> dict[str, Any]:
    """Current price for one symbol, crypto or equity.

    Resolves through whichever upstream answers and names it in the response,
    so a figure can be attributed. Use `BTCUSDT` for crypto pairs and `NVDA`
    for equities.
    """
    try:
        return {"ok": True, **await client.get(f"/api/price/{symbol}")}
    except NotFound:
        return {
            "ok": False,
            "reason": f"The instance could not resolve {symbol!r}. Check the "
            "form — crypto is BTCUSDT, an equity is the plain ticker.",
        }
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_technical_levels(symbol: str) -> dict[str, Any]:
    """Support and resistance zones, trend and RSI for one symbol, computed
    across several timeframes.

    This is the tool for "where are the levels", "is it overbought", "does the
    weekly agree with the daily". Each zone carries the timeframes that
    confirmed it and a strength score: a band agreed on by 1d+1w is a far
    stronger claim than one seen only on 4h, and that confluence is the whole
    point of the endpoint. Do not recompute any of this from candles.
    """
    try:
        return {"ok": True, **await client.get(f"/api/technical/{symbol}")}
    except NotFound:
        return {
            "ok": False,
            "reason": f"No levels could be computed for {symbol!r} — usually "
            "too little history, or the wrong symbol form.",
        }
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_candles(symbol: str, interval: str = "1d", limit: int = 200) -> dict[str, Any]:
    """Raw OHLCV candles for one symbol.

    Only when the series itself is needed — for a chart, or a calculation the
    terminal does not already do. For levels, trend or RSI use
    get_technical_levels instead; it is cheaper and it agrees with the UI.
    """
    try:
        payload = await client.get(
            f"/api/market/candles/{symbol}",
            {"interval": interval, "limit": limit},
        )
    except NotFound:
        return {"ok": False, "reason": f"No candles for {symbol!r}."}
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, "candles": payload}


@server.tool()
async def get_asset_fundamentals(symbol: str) -> dict[str, Any]:
    """Company fundamentals for an equity: P/E, sector, 52-week range,
    analyst targets.

    Equities only. The underlying route defaults to a crypto lookup that
    resolves through CoinGecko, so this tool always asks for the stock branch —
    passing a crypto pair here will not work.
    """
    try:
        payload = await client.get(f"/api/asset-detail/{symbol}", {"type": "stock"})
    except NotFound:
        return {"ok": False, "reason": f"No fundamentals for {symbol!r}."}
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, **payload}


@server.tool()
async def get_market_overview() -> dict[str, Any]:
    """The crypto market in one payload: top coins by market cap, dominance,
    global volume, and the fear & greed reading.

    The tool for "how is the market doing" when no particular asset was named.
    """
    try:
        return {"ok": True, **await client.get("/api/market-overview")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_market_indices() -> dict[str, Any]:
    """Global equity and currency indices — S&P 500, NASDAQ, Nikkei, FTSE,
    DAX, DXY, BIST.

    Served from the macro board's cache, so these numbers agree with the macro
    page rather than drifting from it by a few minutes.
    """
    try:
        return {"ok": True, **await client.get("/api/market/indices")}
    except OracleXError as error:
        return _fail(error)


# ── News ────────────────────────────────────────────────────────────────────


@server.tool()
async def list_news(asset_type: str = "crypto", limit: int = 20) -> dict[str, Any]:
    """Recent headlines from the terminal's feed, with their ids.

    `asset_type` is "crypto" or "stock". Take an id from here and pass it to
    get_news_analysis for the terminal's own read of that article.
    """
    try:
        payload = await client.get("/api/news", {"asset_type": asset_type, "limit": limit})
    except OracleXError as error:
        return _fail(error)
    return {
        "ok": True,
        "items": payload.get("items", []),
        "total": payload.get("total"),
    }


@server.tool()
async def get_news_analysis(news_id: str) -> dict[str, Any]:
    """The terminal's LLM analysis of one article: sentiment, mechanism, risk
    level, invalidation, and historical precedents with how price actually
    resolved after each.

    The precedents are the reason to prefer this over reading the headline
    yourself — they come from this instance's own memory of past events, with
    the realised price change attached.

    If nothing has been analysed yet this starts the job and waits briefly. A
    `pending` result is not a failure; call again in a minute.
    """
    try:
        cached = await client.get(f"/api/news/{news_id}/analysis")
        if cached:
            return {"ok": True, **cached}

        job = await client.post(f"/api/news/{news_id}/analysis/jobs")
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            return {"ok": False, "reason": f"Analysis job returned no id: {job}"}

        for _ in range(20):
            await asyncio.sleep(3)
            state = await client.get(f"/api/news/analysis/jobs/{job_id}")
            status = state.get("status")
            if status in {"completed", "done", "finished"}:
                return {"ok": True, **(state.get("result") or state)}
            if status in {"failed", "error", "cancelled"}:
                return {"ok": False, "reason": state.get("error", status)}

        return {
            "ok": False,
            "pending": True,
            "job_id": job_id,
            "reason": "Analysis is still running. Call again shortly.",
        }
    except NotFound:
        return {"ok": False, "reason": f"No article with id {news_id!r}."}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def find_similar_news(title: str, summary: str = "") -> dict[str, Any]:
    """Find past events in the instance's memory that resemble a headline, and
    what price did after each.

    Use it to separate a story with precedent from one without. The response
    reports the dominant outcome and the average move, and flags the cases
    where the market went against what the headline implied.
    """
    try:
        payload = await client.post(
            "/api/rag/news-similarity", {"title": title, "summary": summary}
        )
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, **payload}


# ── Reports, macro, chains ──────────────────────────────────────────────────


@server.tool()
async def get_analysis_report(timeframe: str = "daily") -> dict[str, Any]:
    """The terminal's stored long-form market report for a timeframe —
    executive summary, technicals, derivatives, macro cross-read, scenarios
    with probabilities, and key levels.

    `timeframe` is "daily" or "weekly". Reading never triggers generation, so
    an empty report means none has been generated yet rather than a failure.
    """
    try:
        return {"ok": True, **await client.get(f"/api/analysis/report/{timeframe}")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_macro_regime() -> dict[str, Any]:
    """The cross-asset regime: a computed label and score for what kind of
    market this is, plus a written note explaining it.

    The label and score are always present. The note is generated by the model
    layer and may be absent, still being written, or unavailable when that
    layer is off — report the label without waiting for it.
    """
    try:
        return {"ok": True, **await client.get("/api/macro/regime")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_macro_board() -> dict[str, Any]:
    """The macro backdrop: indices, metals, commodities and the ratios between
    them (gold/silver, gold/oil), with the dollar index.

    The evidence behind get_macro_regime's label.
    """
    try:
        return {"ok": True, **await client.get("/api/macro/board")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_chains_board() -> dict[str, Any]:
    """Per-chain activity: block times, fees in native units and USD,
    congestion, and throughput across Bitcoin, the EVM chains, Solana and Tron.

    An unmeasurable reading comes back as null rather than zero — the two mean
    opposite things and must not be reported the same way. A chain that could
    not be read at all carries an `error` and all-null metrics.

    The per-chain list of recent blocks is dropped here; it feeds a sparkline
    in the UI and is a third of the payload.
    """
    try:
        board = await client.get("/api/chains/board")
    except OracleXError as error:
        return _fail(error)

    chains = [
        {key: value for key, value in row.items() if key != "blocks"}
        for row in board.get("chains", [])
    ]
    return {"ok": True, **{**board, "chains": chains}}


@server.tool()
async def get_chain_anomalies() -> dict[str, Any]:
    """Chains currently behaving unusually — fee spikes, congestion, stalled
    blocks, mempool build-up.

    Each chain is measured against its own history, not a shared threshold, so
    "fees elevated on Solana" means elevated for Solana.
    """
    try:
        return {"ok": True, **await client.get("/api/chains/anomalies")}
    except OracleXError as error:
        return _fail(error)


# ── Derivatives, flow, ownership ────────────────────────────────────────────


@server.tool()
async def get_liquidation_map(symbol: str, top_clusters: int = 6) -> dict[str, Any]:
    """Where leverage is stacked around current price for one symbol — the
    price levels that would trigger the largest liquidations if reached.

    Pairs with get_technical_levels: the levels say where price may go, this
    says what happens when it arrives. Clusters above current price are where
    short positions unwind, clusters below are where longs do.

    Returns the largest clusters on each side rather than the raw payload. The
    endpoint answers with a rendering grid — roughly eight thousand cells and
    a candle series, a few hundred kilobytes — which is the wrong object to put
    in a model's context and says nothing a summary does not.
    """
    try:
        payload = await client.get(f"/api/liquidations/map/{symbol}")
    except NotFound:
        return {"ok": False, "reason": f"No liquidation map for {symbol!r}."}
    except OracleXError as error:
        return _fail(error)
    return _summarize_liquidation_map(payload, top_clusters)


def _summarize_liquidation_map(payload: dict[str, Any], top: int) -> dict[str, Any]:
    """Reduce the heatmap grid to the clusters that matter.

    Cells are `[column, row, value, _]`, where the column is a time step and
    the row is a price bin. The map accumulates over time, so summing every
    column counts the same exposure repeatedly — the current state is the
    newest column alone, which is also the one `max_value` is computed from.
    """
    cells = payload.get("cells") or []
    candles = payload.get("candles") or []
    bin_size = payload.get("bin_size")
    price_min = payload.get("price_min")

    if not cells or not bin_size or price_min is None:
        return {
            "ok": False,
            "reason": "The map came back without a usable grid.",
        }

    latest_column = max(cell[0] for cell in cells)
    by_bin: dict[int, float] = {}
    for column, row, value, *_ in cells:
        if column == latest_column:
            by_bin[row] = by_bin.get(row, 0) + value

    spot = candles[-1].get("close") if candles else None

    clusters = []
    for row, notional in by_bin.items():
        # An occupied cell can still carry zero notional. Reporting those as
        # clusters fills the answer with levels where nothing is at risk, and
        # ranking by size then puts them first whenever one side is genuinely
        # empty — which reads as "here is where the liquidations are" for a
        # side that has none.
        if not notional:
            continue
        low = price_min + row * bin_size
        cluster: dict[str, Any] = {
            "price_low": round(low, 2),
            "price_high": round(low + bin_size, 2),
            "notional_usd": round(notional),
        }
        if spot:
            cluster["distance_percent"] = round((low - spot) / spot * 100, 2)
            cluster["side"] = "above" if low > spot else "below"
        clusters.append(cluster)

    clusters.sort(key=lambda c: -c["notional_usd"])
    above = [c for c in clusters if c.get("side") == "above"][:top]
    below = [c for c in clusters if c.get("side") == "below"][:top]

    result: dict[str, Any] = {
        "ok": True,
        "symbol": payload.get("symbol"),
        "current_price": spot,
        "total_notional_usd": round(sum(by_bin.values())),
        "bin_size": bin_size,
        "price_range": [payload.get("price_min"), payload.get("price_max")],
        "note": (
            f"Summarized from {len(cells)} grid cells; the largest clusters "
            f"per side out of {len(clusters)} price bins carrying exposure."
        ),
    }

    # An empty side is a finding, not a gap. "Nothing stacked above spot" is
    # what a short squeeze looks like beforehand, and silently omitting the key
    # would let a reader assume the tool simply did not look.
    if spot is None:
        result["clusters"] = clusters[:top]
        result["note"] += " No candle series came back, so nothing is anchored to spot."
    else:
        result["clusters_above"] = above
        result["clusters_below"] = below
        if not above:
            result["note"] += " No exposure is stacked above the current price."
        if not below:
            result["note"] += " No exposure is stacked below the current price."

    return result


@server.tool()
async def get_funding_rates() -> dict[str, Any]:
    """Perpetual funding rates across tracked symbols — which side is paying,
    and therefore how positioning is leaning.
    """
    try:
        return {"ok": True, **await client.get("/api/home/funding-rates")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_whale_flow() -> dict[str, Any]:
    """Recent large transactions with their direction — whether big money is
    accumulating or distributing right now.
    """
    try:
        return {"ok": True, **await client.get("/api/onchain/whales")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_ownership(symbol: str) -> dict[str, Any]:
    """Institutional holders of one equity and the size of their positions."""
    try:
        return {"ok": True, **await client.get(f"/api/ownership/assets/{symbol}")}
    except NotFound:
        return {"ok": False, "reason": f"No ownership data for {symbol!r}."}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_ownership_moves() -> dict[str, Any]:
    """What institutional holders changed recently — the position deltas rather
    than the standing positions.
    """
    try:
        return {"ok": True, **await client.get("/api/ownership/moves")}
    except OracleXError as error:
        return _fail(error)


# ── Memory ──────────────────────────────────────────────────────────────────


@server.tool()
async def search_memory(query: str, symbol: str = "", context_type: str = "all") -> dict[str, Any]:
    """Search the instance's vector memory of past market events, prices and
    news for anything resembling a described situation.

    This is the capability a search engine cannot replace: the store holds what
    this instance actually observed, so "has this setup happened before" is
    answerable with what followed each time. `context_type` is "all", "events",
    "prices" or "news".
    """
    params: dict[str, Any] = {"q": query, "context_type": context_type}
    if symbol:
        params["symbol"] = symbol
    try:
        return {"ok": True, **await client.get("/api/rag/query", params)}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_symbol_history(symbol: str) -> dict[str, Any]:
    """What the memory holds about one symbol — the events behind its past
    moves, not just its price series.
    """
    try:
        return {"ok": True, **await client.get(f"/api/rag/insights/{symbol}")}
    except NotFound:
        return {"ok": False, "reason": f"The memory holds nothing on {symbol!r}."}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def compare_assets(symbol_a: str, symbol_b: str) -> dict[str, Any]:
    """Compare two assets against each other using the stored history.

    One call rather than two lookups the caller then has to reconcile.
    """
    try:
        payload = await client.get(f"/api/rag/compare/{symbol_a}/{symbol_b}")
    except NotFound:
        return {"ok": False, "reason": f"Cannot compare {symbol_a!r} and {symbol_b!r}."}
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, **payload}


@server.tool()
async def get_daily_brief() -> dict[str, Any]:
    """The terminal's own start-of-day briefing, drawn from its memory and the
    current state of the market.
    """
    try:
        return {"ok": True, **await client.get("/api/rag/daily-brief")}
    except OracleXError as error:
        return _fail(error)


# ── The Oracle itself ───────────────────────────────────────────────────────


@server.tool()
async def ask_oracle(question: str, session_id: str = "") -> dict[str, Any]:
    """Put an open-ended question to the terminal's own reasoning layer, which
    has every tool above plus the memory and a planner.

    For questions with a factual answer — a price, a level, a holder list —
    call the specific tool instead. This one runs a full planning pass on the
    operator's own model budget, and for a single number that is a worse answer
    at a higher cost.

    Requires ORACLE_X_TOKEN.
    """
    body: dict[str, Any] = {"message": question}
    if session_id:
        body["session_id"] = session_id

    try:
        status = await client.get("/api/chat/status")
        if not status.get("available", status.get("ok", False)):
            return {
                "ok": False,
                "reason": "No model provider is serving this instance right "
                "now. The data tools still work.",
            }

        job = await client.post("/api/chat/jobs", body, authenticated=True)
        job_id = job.get("job_id") or job.get("id")
        if not job_id:
            return {"ok": False, "reason": f"Chat job returned no id: {job}"}

        for _ in range(60):
            await asyncio.sleep(2)
            state = await client.get(f"/api/chat/jobs/{job_id}", authenticated=True)
            if state.get("status") in {"completed", "done", "finished"}:
                result = state.get("result") or state
                return {"ok": True, **result}
            if state.get("status") in {"failed", "error", "cancelled"}:
                return {"ok": False, "reason": state.get("error", "the turn failed")}

        return {
            "ok": False,
            "pending": True,
            "job_id": job_id,
            "reason": "The Oracle is still thinking. Do not start a second "
            "turn — poll this job id instead.",
        }
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_watchlist() -> dict[str, Any]:
    """The signed-in user's own tracked symbols.

    Requires ORACLE_X_TOKEN.
    """
    try:
        payload = await client.get("/api/home/watchlist", authenticated=True)
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, "watchlists": payload}


def main() -> None:
    """Run over stdio, which is how MCP clients launch a local server."""
    server.run()


if __name__ == "__main__":
    main()
