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
    version="1.4.0",
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
        "BINANCE:ETHUSDT, equities are the plain ticker (NVDA). Borsa "
        "İstanbul is the exception and has its own tools — a bare Turkish "
        "ticker will not resolve through get_price.\n\n"
        "Every Borsa İstanbul return arrives as nominal, real and usd "
        "together. Quote the lira figure alone and you have reported "
        "inflation as performance; say which frame you are quoting, and when "
        "real is null say it is unavailable rather than passing the nominal "
        "number off in its place."
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


# ── Borsa İstanbul ──────────────────────────────────────────────────────────

# Six tools for thirty-two endpoints, on the same reasoning as the prediction
# markets above: a tool list is context every turn pays for, so what is here is
# the questions a person actually asks about this market. Deliberately absent —
# the ownership book, the entity-level positioning detail and the radar screen.
# The first two are second-order questions best reached through the HTTP API
# once the board has raised them, and the radar is a job that has to be polled,
# which is a poor shape for a tool the model expects to answer in one turn.


@server.tool()
async def get_bist_overview() -> dict[str, Any]:
    """The Turkish market in one payload: the indices, the movers and the
    written read of the session.

    The tool for "how is Borsa İstanbul doing" when no ticker was named.
    Quotes here are delayed at least fifteen minutes and the payload says so
    in `delay_minutes` — never present one as live.
    """
    try:
        return {"ok": True, **await client.get("/api/bist/overview")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_bist_stock(ticker: str) -> dict[str, Any]:
    """One Borsa İstanbul name: price, and what it actually returned.

    Pass the bare ticker — `THYAO`, `ASELS`, `GARAN`. Everywhere else in this
    terminal a symbol carries its venue, and a bare Turkish ticker will not
    resolve through get_price; this tool is the Turkish branch.

    **Read the return frames before quoting a number.** Every window comes back
    as `nominal`, `real` and `usd` together. Over a year in which consumer
    prices rose about a third, quoting the lira figure alone reports inflation
    as performance — it is the most common way to be wrong about this market
    and it looks entirely reasonable on the page. A null `real` means the
    window could not be deflated, never that inflation was zero.
    """
    try:
        return {"ok": True, **await client.get(f"/api/bist/stocks/{ticker}")}
    except NotFound:
        return {
            "ok": False,
            "reason": f"{ticker!r} did not resolve on Borsa İstanbul. Check the "
            "spelling rather than substituting a figure — this is a refusal, "
            "not a gap.",
        }
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_bist_fund(code: str) -> dict[str, Any]:
    """A TEFAS fund: its own numbers, and what it is actually holding.

    Two calls behind one tool, because "how did this fund do" and "what is in
    it" are never asked apart. The same three return frames apply as for a
    stock. If the holdings call fails the fund's own figures are still
    returned, with the gap named rather than left blank.
    """
    try:
        fund = await client.get(f"/api/bist/funds/{code}")
    except NotFound:
        return {"ok": False, "reason": f"No TEFAS fund with code {code!r}."}
    except OracleXError as error:
        return _fail(error)

    result: dict[str, Any] = {"ok": True, "fund": fund}
    try:
        result["holdings"] = await client.get(f"/api/bist/funds/{code}/holdings")
    except OracleXError as error:
        result["holdings_unavailable"] = str(error)
    return result


@server.tool()
async def get_bist_disclosures(limit: int = 20) -> dict[str, Any]:
    """KAP filings — what listed companies have formally disclosed.

    The tool for "did anything happen at this company". Material disclosures
    move Turkish equities more reliably than news coverage does, because the
    coverage is usually downstream of the filing.
    """
    try:
        return {"ok": True, **await client.get("/api/bist/kap", {"limit": limit})}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_turkish_macro() -> dict[str, Any]:
    """The Turkish macro backdrop: inflation, the policy rate and the exchange
    rate.

    These are the series every `real` figure elsewhere in this market is
    deflated by, so this is the tool that explains why a nominal return and a
    real one disagree, rather than a separate subject.
    """
    try:
        return {"ok": True, **await client.get("/api/bist/macro")}
    except OracleXError as error:
        return _fail(error)


@server.tool()
async def get_viop_positioning(ticker: str, top_bands: int = 6) -> dict[str, Any]:
    """Where VİOP positions sit for one underlying, and how far each cohort is
    from the scan range its margin was sized against.

    **The band is not a margin call and must never be reported as one.** It is
    Takasbank's published price scan range: the one-day, 99% confidence move
    the clearing house collateralised a position's *initial* margin against.
    VİOP publishes no maintenance margin rate — the CCP procedure leaves the
    level to a General Letter and states maintenance is not applied at end of
    day — so the price at which a call actually fires cannot be computed from
    anything public. The "75% of initial" figure that circulates online traces
    to one undated guide.

    Direction is inferred rather than published: open interest rising into a
    rising settlement reads as longs opening, rising against a falling one as
    shorts. Everything else — exposure, entry price, the swept range, the band
    itself — comes from the exchange or the clearing house.

    Returns the heaviest bands per side rather than the raw grid, which is a
    rendering object of thousands of cells.
    """
    try:
        payload = await client.get(f"/api/bist/viop-map/{ticker}")
    except NotFound:
        return {
            "ok": False,
            "reason": f"No VİOP map for {ticker!r}. The map is built only where "
            "the data supports it and coverage is narrower than the exchange's "
            "contract list, so this may be a covered market with too little "
            "open interest rather than a bad ticker.",
        }
    except OracleXError as error:
        return _fail(error)
    return _summarize_viop_map(payload, top_bands)


def _summarize_viop_map(payload: dict[str, Any], top: int) -> dict[str, Any]:
    """Reduce the positioning grid to the bands carrying the most notional.

    Cells are `{column, bin_index, long_try, short_try}` and the map
    accumulates across sessions, so a level that survived ten sessions appears
    in ten cells. Summing every column would therefore count the same exposure
    ten times; the current state is the newest column alone.
    """
    cells = payload.get("cells") or []
    bin_size = payload.get("bin_size")
    price_min = payload.get("price_min")

    if not cells or not bin_size or price_min is None:
        return {"ok": False, "reason": "The map came back without a usable grid."}

    latest = max(cell["column"] for cell in cells)
    bands: list[dict[str, Any]] = []
    for cell in cells:
        if cell["column"] != latest:
            continue
        long_try = cell.get("long_try") or 0.0
        short_try = cell.get("short_try") or 0.0
        if not (long_try or short_try):
            continue
        low = price_min + cell["bin_index"] * bin_size
        bands.append(
            {
                "price_low": round(low, 2),
                "price_high": round(low + bin_size, 2),
                "long_try": round(long_try),
                "short_try": round(short_try),
                "side": "long" if long_try >= short_try else "short",
            }
        )

    bands.sort(key=lambda b: -(b["long_try"] + b["short_try"]))
    psr = payload.get("psr")

    result: dict[str, Any] = {
        "ok": True,
        "underlying": payload.get("underlying"),
        "price_scan_range_percent": round(psr * 100, 2) if isinstance(psr, (int, float)) else psr,
        "open_interest": payload.get("open_interest"),
        "thin": payload.get("thin"),
        "price_range": [payload.get("price_min"), payload.get("price_max")],
        "longs": [b for b in bands if b["side"] == "long"][:top],
        "shorts": [b for b in bands if b["side"] == "short"][:top],
        "caveat": (
            "price_scan_range_percent is the move initial margin was sized "
            "for, not a margin-call level. VİOP publishes no maintenance "
            "margin rate, so no call price can be derived from this."
        ),
        "note": (
            f"Summarized from {len(cells)} grid cells across "
            f"{len(payload.get('sessions') or [])} sessions; the newest session "
            f"alone, since the map accumulates and older columns repeat the "
            f"same exposure."
        ),
    }

    # A session whose settlement did not move yields no cohort at all rather
    # than a hedged split, so an unclassified count is expected and saying how
    # much went unread is the difference between a thin map and a wrong one.
    if payload.get("undirected_sessions"):
        result["undirected_sessions"] = payload["undirected_sessions"]
        result["note"] += (
            f" {payload['undirected_sessions']} session(s) closed flat and could "
            "not be assigned a direction; their exposure is not in the bands."
        )
    if payload.get("thin"):
        result["note"] += " Open interest is below the floor this map is reliable at."

    return result


# ── Prediction markets ──────────────────────────────────────────────────────
#
# Three tools rather than one per route. The tool list is context every turn
# pays for, and these are the three questions a person actually asks: what are
# the odds, what does this one market look like, and why.


@server.tool()
async def get_prediction_markets(category: str = "") -> dict[str, Any]:
    """Live prediction markets, busiest first.

    What people are betting happens next, priced by real money. Use it when the
    question is about the *probability* of an event rather than the price of an
    asset — an election, a ceasefire, a rate decision, a match.

    `category` filters to one of politics, geopolitics, macro, crypto, sports.
    Leave it empty for everything.

    A price here is what traders believe. It is evidence about the crowd, not
    about the world, and it should never be cited as a reason the event will
    happen.
    """
    try:
        payload = await client.get("/api/polymarket/board")
    except OracleXError as error:
        return _fail(error)

    markets = payload.get("markets", [])
    if category:
        markets = [m for m in markets if m.get("category") == category]
    return {
        "ok": True,
        "markets": markets,
        "stale": payload.get("stale", False),
        "age_seconds": payload.get("age_seconds", 0),
    }


@server.tool()
async def get_prediction_market(slug: str) -> dict[str, Any]:
    """One market's odds, movement and holder concentration.

    Everything here is measured — no model is consulted, so this is cheap and
    always available. It includes the windows in which the price moved sharply,
    which is what `analyse_prediction_market` searches news inside.

    `top_holder_share` is the reading worth looking at: the same price set by
    four hundred wallets and by one whale are different facts.
    """
    try:
        payload = await client.get(f"/api/polymarket/markets/{slug}")
    except NotFound:
        return {"ok": False, "reason": f"No market matches {slug!r}."}
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, **payload}


@server.tool()
async def analyse_prediction_market(slug: str) -> dict[str, Any]:
    """Start a sourced analysis of one market, and return the job to poll.

    Searches the news, reads what it finds, traces the market's sharp price
    moves to dated stories, and weighs both sides. It takes a couple of minutes,
    so this returns a job — poll `get_analysis_job` with the returned id.

    **It may refuse, and a refusal is a result, not a failure.** When the
    evidence gathered does not clear the bar for a judgement, the verdict comes
    back with `status: "insufficient_evidence"` and an explanation naming every
    search that was run and every one that came back empty. Report that as the
    answer rather than retrying or filling the gap yourself — the market's odds
    and movement are still in the payload and are still measured.
    """
    try:
        payload = await client.post(f"/api/polymarket/markets/{slug}/analysis/jobs", {})
    except NotFound:
        return {"ok": False, "reason": f"No market matches {slug!r}."}
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, "job_id": payload.get("job_id"), "status": payload.get("status")}


@server.tool()
async def get_prediction_analysis_job(job_id: str) -> dict[str, Any]:
    """Poll a running prediction-market analysis.

    `status` is queued, running, done or error. When it is done, `result` holds
    either a verdict or a refusal — check `result.status` before reading further.
    """
    try:
        payload = await client.get(f"/api/polymarket/analysis/jobs/{job_id}")
    except NotFound:
        return {"ok": False, "reason": "That analysis job has expired."}
    except OracleXError as error:
        return _fail(error)
    return {"ok": True, **payload}


def main() -> None:
    """Run over stdio, which is how MCP clients launch a local server."""
    server.run()


if __name__ == "__main__":
    main()
