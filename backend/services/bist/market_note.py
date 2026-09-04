"""
What the whole board says, for the two screeners that only show its rows.

`/bist/hisseler` prints six hundred companies and `/bist/fonlar` two thousand
funds, sorted and filtered. Both are correct and neither can answer the question
a reader actually arrives with, because the answer is a property of the *set*:

* whether the index and the breadth agree. An index carried up by five names
  while most of the board fell is a different market from one where everything
  rose, and no row shows it — the column that would is the whole column.
* whether the median fund beat inflation, and how far apart the best and worst
  in the same category ended. A table sorted by return puts the winners on top
  by construction, which is the one arrangement that cannot show dispersion.

So this module aggregates, classifies in Python, and hands `services/ai_notes`
a finished set of facts to narrate. The model scores nothing and never sees an
unrounded number — the same contract `ownership/flow_note.py` and
`macro_regime.py` hold to, and for the same reason: a local model asked to do
arithmetic will do it confidently and wrongly.

**Bucketing is load-bearing here, not tidiness.** The equity board refreshes
every two minutes. Fingerprinting a raw `change_pct` would retire the note on
every poll, so the cache would never hit and a machine running a local model
would write market commentary forever. Every volatile reading is therefore
quantized to a step coarse enough that an unchanged market is an unchanged
fingerprint, and — the part that matters for correctness — the prompt is
rendered from those same bucketed values, so a cached note can never quote a
figure that has since moved.

Nothing here raises. A note is a paragraph above a board that is already
complete, so every failure comes back as `unavailable` and the panel keeps its
deterministic header.
"""

import logging
import statistics
from typing import Any

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)
from services.bist.equity_service import (
    EquityBoard,
    EquityDataUnavailable,
    SectorStat,
    fetch_equity_board,
    sector_performance,
)
from services.bist.fund_service import (
    FundBoard,
    FundDataUnavailable,
    fetch_fund_board,
)
from services.bist.macro_service import (
    WINDOW_MONTHS,
    MacroSnapshot,
    MacroUnavailable,
    deflator_for_window,
    fetch_cpi_series,
    fetch_macro_snapshot,
    fetch_usdtry_series,
)
from services.bist.real_return import enrich_returns, summarise_real_losses
from services.bist.sentiment_service import compute_dominance, compute_sentiment
from services.bist.tefas_client import FundRow
from services.bist.tradingview_client import EquityRow, IndexRow
from services.bist.viop_service import fetch_viop_board, summarise

logger = logging.getLogger(__name__)

UNKNOWN = "not available"

# The headline index. XU100 rather than XUTUM because it is the number every
# Turkish reader already has in their head, and the one the breadth below is
# worth contradicting.
HEADLINE_INDEX = "XU100"

MARKET_SPEC = NoteSpec(
    kind="bist_market",
    prompt="notes/bist_market",
    # A market-wide read weaves a dozen readings rather than describing one
    # instrument, so it gets roughly twice the room `bist_brief` has.
    max_tokens=560,
    max_chars=1400,
    # Slightly above the 0.2 the single-instrument notes use. This paragraph has
    # to connect readings rather than restate one, and at 0.2 the local model
    # produced the same four clauses in the same order every session.
    temperature=0.25,
    # A session's worth. The bucketed facts retire the note whenever the market
    # actually moves; this only covers the quiet stretch where nothing crossed a
    # step and the reading is nonetheless hours old.
    max_age_seconds=4 * 3600,
)

FUNDS_MARKET_SPEC = NoteSpec(
    kind="bist_funds_market",
    prompt="notes/bist_funds_market",
    max_tokens=560,
    max_chars=1400,
    temperature=0.25,
    # Net asset values publish once, after the close, so nothing this note says
    # can change intraday.
    max_age_seconds=24 * 3600,
)

# What this read cannot see. Stated to the reader and to the model rather than
# left implicit, on `macro_regime.NOT_MEASURED`'s reasoning: a call made from
# breadth, valuation and one macro print can be right about everything in front
# of it and still miss the day's actual driver.
NOT_MEASURED: tuple[str, ...] = (
    "oynaklık endeksi",
    "tahvil faizleri ve verim eğrisi",
    "kredi risk primi",
    "yabancı takas oranı",
)

# ── Stance thresholds ────────────────────────────────────────────────────────
#
# Deadbands rather than a sign test. A board that closed at +0.04% has not
# rallied, and calling it one flips the read on noise from one poll to the next.

INDEX_DEADBAND_PCT = 0.3
"""Percentage points the index must clear before the day has a direction."""

NARROW_ADVANCER_PCT = 45.0
BROAD_ADVANCER_PCT = 60.0
NARROW_SELLOFF_ADVANCER_PCT = 55.0
BROAD_SELLOFF_ADVANCER_PCT = 40.0

# Above this share of the session's turnover in five names, the index is a
# handful of stocks wearing a market's name.
CONCENTRATION_PCT = 30.0

STANCE_NARROW_RALLY = "narrow_rally"
STANCE_BROAD_RALLY = "broad_rally"
STANCE_NARROW_SELLOFF = "narrow_selloff"
STANCE_BROAD_SELLOFF = "broad_selloff"
STANCE_MIXED = "mixed"

# Below this the board is a handful of quotes, not a market to characterise.
MIN_EQUITIES = 50

TOP_SECTORS = 3
# A "sector" of two listings is a company, and its move is that company's move.
MIN_SECTOR_MEMBERS = 3

# ── Fund thresholds ──────────────────────────────────────────────────────────

FUND_STANCE_BEATING = "beating_inflation"
FUND_STANCE_LOSING = "losing_to_inflation"
FUND_STANCE_SPLIT = "split"

FUND_BEATING_PCT = 60.0
FUND_LOSING_PCT = 40.0

MIN_FUNDS = 20
MIN_MEASURED_FUNDS = 10
TOP_UMBRELLAS = 3
# Fewer than this and the "best category" is one lucky fund wearing a category's
# name — the same failure the sector floor above guards against.
MIN_UMBRELLA_MEMBERS = 5

RISK_COHORTS: tuple[tuple[str, str, int, int], ...] = (
    ("low", "1–3", 1, 3),
    ("mid", "4–5", 4, 5),
    ("high", "6–7", 6, 7),
)


# ── Quantization ─────────────────────────────────────────────────────────────


def _zeroed(value: float) -> float:
    """
    Rounding turns a small negative into `-0.0`, which renders as "-0.0%".

    Harmless arithmetic and a bad sentence: the model quotes the reading
    verbatim, so a board that barely moved was described as having fallen by
    negative zero. Borrowed from `macro_regime._zeroed` for the same reason.
    """
    return 0.0 if value == 0 else value


def _bucket(value: float | None, step: float) -> float | None:
    """Snap to a multiple of `step`. The whole cache design rests on this."""
    if value is None:
        return None
    return _zeroed(round(round(value / step) * step, 4))


def _pct(value: float | None, digits: int = 1) -> float | None:
    """A fraction as rounded percentage points, or None."""
    if value is None:
        return None
    try:
        return _zeroed(round(float(value) * 100, digits))
    except (TypeError, ValueError):
        return None


def _pct_bucket(value: float | None, step: float) -> float | None:
    """A fraction as percentage points, snapped to `step`."""
    return _bucket(_pct(value, 4), step)


def _num(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return _zeroed(round(float(value), digits))
    except (TypeError, ValueError):
        return None


def _day(stamp: str | None) -> str | None:
    """
    An ISO stamp as a bare date.

    Both stamps this module carries are quantized this way for the same reason
    every figure above is bucketed: `MacroSnapshot.as_of` has microseconds on it,
    so fingerprinting it raw would retire the note on every macro refresh — a
    regeneration triggered by nothing the reader could see.
    """
    return (stamp or "")[:10] or None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _percentile(values: list[float], fraction: float) -> float | None:
    """
    Nearest-rank percentile.

    `statistics.quantiles` needs at least two points and interpolates; this is
    used on cohorts that may be small, and a rank is easier to defend in a
    sentence than an interpolated value nobody's fund actually returned.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


# ── Rendering helpers ────────────────────────────────────────────────────────


def _show_pct(value: float | None, sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.1f}%" if sign else f"{value:.1f}%"


def _show_num(value: float | None, digits: int = 1) -> str:
    return UNKNOWN if value is None else f"{value:.{digits}f}"


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


# ══════════════════════════════════════════════════════════════════════════
# Equities
# ══════════════════════════════════════════════════════════════════════════


def _headline_index(indices: list[IndexRow]) -> IndexRow | None:
    return next((row for row in indices if row.code == HEADLINE_INDEX), None)


def classify_stance(index_change_pct: float | None, advancer_pct: float | None) -> str:
    """
    The day's read: did the index and the breadth agree, and which way.

    This is the one classification on the equity board that no row can show, and
    it is the first thing a professional checks — an index carried by a handful
    of names is a different market from one the whole board took part in, and
    the headline figure is identical in both.
    """
    if index_change_pct is None or advancer_pct is None:
        return STANCE_MIXED

    if index_change_pct >= INDEX_DEADBAND_PCT:
        if advancer_pct < NARROW_ADVANCER_PCT:
            return STANCE_NARROW_RALLY
        if advancer_pct >= BROAD_ADVANCER_PCT:
            return STANCE_BROAD_RALLY
        return STANCE_MIXED

    if index_change_pct <= -INDEX_DEADBAND_PCT:
        if advancer_pct > NARROW_SELLOFF_ADVANCER_PCT:
            return STANCE_NARROW_SELLOFF
        if advancer_pct <= BROAD_SELLOFF_ADVANCER_PCT:
            return STANCE_BROAD_SELLOFF
        return STANCE_MIXED

    return STANCE_MIXED


def _tail(ranked: list, top: int) -> list:
    """
    The bottom `top` entries, worst first, and never one already at the top.

    Without the overlap guard a board with three sectors would report all three
    as leading and the same three as lagging, which reads as a bug and is one:
    "led by X, held back by X" is not a finding. Live boards carry twenty
    sectors and a dozen umbrella types, so this only fires on a thin board —
    which is exactly when a reader would be least able to spot it.
    """
    if len(ranked) <= top:
        return []
    return list(reversed(ranked[-top:]))


def _sector_entry(stat: SectorStat) -> dict[str, Any]:
    return {
        "sector": stat.sector,
        "count": stat.count,
        "change_pct": _pct_bucket(stat.change_pct, 0.5),
        "weight_pct": _pct_bucket(stat.weight, 1.0),
        "advancers": stat.advancers,
        "decliners": stat.decliners,
    }


def _valuation(equities: list[EquityRow]) -> dict[str, float | None]:
    """
    Median multiples across the headline index.

    Median rather than mean, and XU100 rather than the whole board: one
    loss-making micro-cap with a P/E of 900 moves a mean enough to make the
    figure a lie, and the reader's mental benchmark is the index anyway.

    Non-positive earnings are excluded rather than counted as zero. A negative
    P/E is not a cheap company; it is a company with no E, and averaging it in
    understates the multiple of the ones that do.
    """
    members = [row for row in equities if HEADLINE_INDEX in row.indices]
    if not members:
        members = equities

    pes = [row.pe for row in members if row.pe is not None and row.pe > 0]
    pbs = [row.pb for row in members if row.pb is not None and row.pb > 0]
    return {
        "median_pe": _num(_median(pes), 1),
        "median_pb": _num(_median(pbs), 2),
        "measured": len(members),
    }


async def _deflators() -> tuple[dict[str, float | None], MacroSnapshot | None, list[dict]]:
    """
    Deflators and the macro print, or empty ones.

    A copy of the router's `_real_return_context` rather than an import of it:
    a service reaching up into a router would invert the dependency this
    codebase is built on. Never raises — a macro outage costs the real column,
    not the note.
    """
    try:
        snapshot = await fetch_macro_snapshot()
    except MacroUnavailable:
        return dict.fromkeys(WINDOW_MONTHS), None, []

    cpi = await fetch_cpi_series()
    fx = await fetch_usdtry_series("5y")
    deflators = {window: deflator_for_window(window, snapshot, cpi) for window in WINDOW_MONTHS}
    return deflators, snapshot, fx


async def _viop_open_interest() -> dict[str, Any] | None:
    """
    Total futures open interest, or None.

    Optional on purpose. It is a genuine positioning reading and it comes from a
    scraped page that is down more often than the rest of this realm, so a
    failure drops the fact and adds the reading to `not_measured` rather than
    costing the paragraph.
    """
    try:
        board = await fetch_viop_board()
    except Exception as e:  # noqa: BLE001 — a note must not take a page down
        logger.info("VİOP open interest unavailable for the market note: %s", e)
        return None

    summary = summarise(board.contracts)
    total = summary.get("total_open_interest")
    if not total:
        return None

    # Bucketed to a thousand lots: open interest is a large integer that moves
    # by a handful of contracts constantly, and the raw figure would retire the
    # note on noise.
    return {"total": _bucket(float(total), 1000.0), "stale": board.stale}


async def build_market_facts() -> dict[str, Any] | None:
    """
    The whole equity board as a quantized set of readings, or None.

    None means the board could not be read or is too thin to characterise —
    which the caller must not render as a quiet market. "Nothing is happening"
    and "we cannot see what is happening" are different claims.
    """
    try:
        board: EquityBoard = await fetch_equity_board()
    except EquityDataUnavailable as e:
        logger.info("Equity board unavailable for the market note: %s", e)
        return None

    if len(board.equities) < MIN_EQUITIES:
        return None

    sectors = sector_performance(board.equities)
    sentiment = compute_sentiment(board.equities)
    dominance = compute_dominance(board.equities, sectors)
    deflators, snapshot, fx = await _deflators()
    viop = await _viop_open_interest()

    index = _headline_index(board.indices)
    index_framed: dict[str, dict] = {}
    if index is not None:
        index_framed = enrich_returns(
            {"1y": index.perf_1y},
            deflators=deflators,
            fx_series=fx,
            window_months=WINDOW_MONTHS,
        )
    year = index_framed.get("1y") or {}

    advancers = sum(1 for row in board.equities if (row.change_pct or 0) > 0)
    decliners = sum(1 for row in board.equities if (row.change_pct or 0) < 0)
    total = len(board.equities)
    advancer_pct = _bucket(advancers / total * 100, 5.0)

    index_change = _pct_bucket(index.change_pct, 0.5) if index else None
    stance = classify_stance(index_change, advancer_pct)

    ranked = [
        stat for stat in sectors if stat.change_pct is not None and stat.count >= MIN_SECTOR_MEMBERS
    ]
    ranked.sort(key=lambda stat: stat.change_pct, reverse=True)

    top5_share = _pct_bucket(dominance.top5_turnover_share, 2.0)
    not_measured = list(NOT_MEASURED)
    if viop is None:
        not_measured.append("VİOP açık pozisyonu")

    return {
        "stance": stance,
        "as_of": _day(board.as_of),
        "stale": board.stale,
        "index": {
            "code": HEADLINE_INDEX,
            "name": index.name if index else None,
            # Bucketed to a hundred points: the level is context for the move,
            # not a quote, and the last two digits move every tick.
            "value": _bucket(index.value, 100.0) if index else None,
            "change_pct": index_change,
            "ytd_pct": _pct_bucket(index.perf_ytd, 1.0) if index else None,
            "year_nominal_pct": _pct_bucket(year.get("nominal"), 1.0),
            "year_real_pct": _pct_bucket(year.get("real"), 1.0),
        },
        "breadth": {
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": total - advancers - decliners,
            "total": total,
            "advancer_pct": advancer_pct,
        },
        "sentiment": (
            {
                "score": _bucket(float(sentiment.score), 2.0),
                "label": sentiment.label,
                "measured": sentiment.measured,
                "components": [
                    {
                        "key": component.key,
                        "label": component.label,
                        "score": _bucket(component.score, 2.0),
                        "reading": component.reading,
                    }
                    for component in sentiment.components
                ],
            }
            if sentiment
            else None
        ),
        "leaders": [_sector_entry(stat) for stat in ranked[:TOP_SECTORS]],
        "laggards": [_sector_entry(stat) for stat in _tail(ranked, TOP_SECTORS)],
        "concentration": {
            "sector": dominance.sector,
            "sector_weight_pct": _pct_bucket(dominance.sector_weight, 1.0),
            "sector_change_pct": _pct_bucket(dominance.sector_change_pct, 0.5),
            "top_ticker": dominance.top_ticker,
            "top_turnover_pct": _pct_bucket(dominance.top_turnover_share, 2.0),
            "top5_turnover_pct": top5_share,
            "concentrated": top5_share is not None and top5_share >= CONCENTRATION_PCT,
        },
        "valuation": _valuation(board.equities),
        "macro": (
            {
                "inflation_pct": _pct(snapshot.inflation_yoy),
                "ppi_pct": _pct(snapshot.ppi_yoy),
                "policy_rate_pct": _pct(snapshot.policy_rate),
                # Fisher, not subtraction. At these levels the difference between
                # the two is several points, and the shortcut would be invisible.
                "real_policy_rate_pct": _pct(
                    (1 + snapshot.policy_rate) / (1 + snapshot.inflation_yoy) - 1
                    if snapshot.policy_rate is not None and snapshot.inflation_yoy is not None
                    else None
                ),
                "unemployment_pct": _pct(snapshot.unemployment),
                "gdp_pct": _pct(snapshot.gdp_yoy),
                "usdtry": _num(snapshot.usdtry, 2),
                "as_of": _day(snapshot.as_of),
            }
            if snapshot
            else None
        ),
        "viop": viop,
        "not_measured": not_measured,
    }


def market_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    index = facts["index"]
    breadth = facts["breadth"]
    concentration = facts["concentration"]
    valuation = facts["valuation"]
    sentiment = facts["sentiment"]
    macro = facts["macro"]

    index_lines = [
        f"- {index['code']} level: {_show_num(index['value'], 0)}",
        f"- {index['code']} today: {_show_pct(index['change_pct'])}",
        f"- {index['code']} year to date: {_show_pct(index['ytd_pct'])}",
        f"- {index['code']} over the trailing year, nominal: {_show_pct(index['year_nominal_pct'])}",
    ]
    if index["year_real_pct"] is None:
        index_lines.append(
            "- Over the trailing year, real: not available — the inflation series "
            "does not cover this window, so the year cannot be read in "
            "purchasing-power terms"
        )
    else:
        index_lines.append(f"- Over the trailing year, real: {_show_pct(index['year_real_pct'])}")
        if (
            index["year_nominal_pct"] is not None
            and index["year_nominal_pct"] > 0 > index["year_real_pct"]
        ):
            index_lines.append(
                "- Note: the index gained in lira and lost in purchasing power over that year"
            )

    breadth_lines = [
        f"- Advancing: {breadth['advancers']} of {breadth['total']} listings "
        f"({_show_pct(breadth['advancer_pct'], sign=False)} of the board)",
        f"- Declining: {breadth['decliners']}; unchanged: {breadth['unchanged']}",
    ]

    if sentiment:
        sentiment_lines = [
            f"- Composite fear & greed: {_show_num(sentiment['score'], 0)} of 100 "
            f"({sentiment['label']}), computed from {sentiment['measured']} shares"
        ] + [
            f"- {component['label']}: scored {_show_num(component['score'], 0)} of 100 "
            f"— measured as {component['reading']}"
            for component in sentiment["components"]
        ]
    else:
        sentiment_lines = [
            "- The fear & greed index could not be computed today — too few shares "
            "carried the readings it needs, so sentiment is unmeasured rather than neutral"
        ]

    def _sector_line(entry: dict[str, Any]) -> str:
        return (
            f"{entry['sector']}: {_show_pct(entry['change_pct'])} "
            f"(capitalisation-weighted, {entry['count']} companies, "
            f"{entry['advancers']} up / {entry['decliners']} down, "
            f"{_show_pct(entry['weight_pct'], sign=False)} of listed market value)"
        )

    concentration_lines = []
    if concentration["sector"]:
        concentration_lines.append(
            f"- Largest sector by market value: {concentration['sector']}, "
            f"{_show_pct(concentration['sector_weight_pct'], sign=False)} of the total, "
            f"moving {_show_pct(concentration['sector_change_pct'])} today"
        )
    if concentration["top_ticker"]:
        concentration_lines.append(
            f"- Busiest share today: {concentration['top_ticker']}, "
            f"{_show_pct(concentration['top_turnover_pct'], sign=False)} of the session's turnover"
        )
    concentration_lines.append(
        f"- The five busiest shares are {_show_pct(concentration['top5_turnover_pct'], sign=False)} "
        "of the session's turnover"
    )
    if concentration["concentrated"]:
        concentration_lines.append(
            "- Note: turnover is unusually concentrated, so the index is tracking a "
            "small number of names rather than the board"
        )

    valuation_lines = [
        f"- Median price/earnings across {index['code']} constituents "
        f"(loss-making companies excluded): {_show_num(valuation['median_pe'], 1)}",
        f"- Median price/book: {_show_num(valuation['median_pb'], 2)}",
    ]

    if macro:
        macro_lines = [
            f"- Annual CPI inflation: {_show_pct(macro['inflation_pct'], sign=False)}",
            f"- Annual producer price inflation: {_show_pct(macro['ppi_pct'], sign=False)}",
            f"- Central bank policy rate: {_show_pct(macro['policy_rate_pct'], sign=False)}",
            f"- Real policy rate (Fisher, not a subtraction): "
            f"{_show_pct(macro['real_policy_rate_pct'])}",
            f"- USDTRY: {_show_num(macro['usdtry'], 2)}",
            f"- Unemployment: {_show_pct(macro['unemployment_pct'], sign=False)}",
            f"- GDP growth year on year: {_show_pct(macro['gdp_pct'])}",
            f"- Macro prints as of {macro['as_of']}",
        ]
    else:
        macro_lines = [
            "- The macro series could not be read, so inflation, the policy rate "
            "and the currency are unknown for this note"
        ]

    if facts["viop"]:
        macro_lines.append(
            f"- Total futures open interest on VİOP: "
            f"{_show_num(facts['viop']['total'], 0)} contracts"
        )

    return {
        "stance": facts["stance"].replace("_", " "),
        "index": "\n".join(index_lines),
        "breadth": "\n".join(breadth_lines),
        "sentiment": "\n".join(sentiment_lines),
        "leaders": _bullet([_sector_line(entry) for entry in facts["leaders"]]),
        "laggards": _bullet([_sector_line(entry) for entry in facts["laggards"]]),
        "concentration": "\n".join(concentration_lines),
        "valuation": "\n".join(valuation_lines),
        "macro": "\n".join(macro_lines),
        "not_measured": ", ".join(facts["not_measured"]),
    }


async def market_note(facts: dict[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    """The note for this board, or `unavailable` when there is nothing to read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(MARKET_SPEC, facts, market_values(facts), user_id)


# ══════════════════════════════════════════════════════════════════════════
# Funds
# ══════════════════════════════════════════════════════════════════════════


def classify_fund_stance(beat_pct: float | None) -> str:
    """Whether the typical fund kept its holder's purchasing power."""
    if beat_pct is None:
        return FUND_STANCE_SPLIT
    if beat_pct >= FUND_BEATING_PCT:
        return FUND_STANCE_BEATING
    if beat_pct <= FUND_LOSING_PCT:
        return FUND_STANCE_LOSING
    return FUND_STANCE_SPLIT


def _umbrella_stats(
    funds: list[FundRow], framed: dict[str, dict[str, dict]]
) -> list[dict[str, Any]]:
    """
    Median real one-year return per şemsiye category, largest first.

    Categories thinner than `MIN_UMBRELLA_MEMBERS` are dropped rather than
    ranked. A "category" of two funds ranked first is one lucky manager wearing
    a category's name, and a reader would take it as a statement about a
    strategy.
    """
    buckets: dict[str, list[tuple[float, float | None]]] = {}
    for fund in funds:
        entry = (framed.get(fund.code) or {}).get("1y")
        if not entry or entry.get("nominal") is None:
            continue
        buckets.setdefault(fund.umbrella or "Bilinmiyor", []).append(
            (entry["nominal"], entry.get("real"))
        )

    rows: list[dict[str, Any]] = []
    for umbrella, pairs in buckets.items():
        if len(pairs) < MIN_UMBRELLA_MEMBERS:
            continue
        reals = [real for _, real in pairs if real is not None]
        rows.append(
            {
                "umbrella": umbrella,
                "count": len(pairs),
                "median_nominal_pct": _pct_bucket(_median([nom for nom, _ in pairs]), 1.0),
                "median_real_pct": _pct_bucket(_median(reals), 1.0),
            }
        )

    # Sorted on the real median where there is one. A ranking on nominal returns
    # in a high-inflation market orders the categories by how much lira they
    # printed, which is the question this whole realm exists to reframe.
    rows.sort(
        key=lambda row: (
            row["median_real_pct"]
            if row["median_real_pct"] is not None
            else row["median_nominal_pct"] or 0.0
        ),
        reverse=True,
    )
    return rows


def _risk_cohorts(funds: list[FundRow], framed: dict[str, dict[str, dict]]) -> list[dict[str, Any]]:
    """
    Median one-year return by TEFAS risk grade — did taking risk pay?

    The screener sorts by return and colours the risk grade, which lets a reader
    see both columns and still not answer this: the question is about the
    cohorts, not the rows.
    """
    cohorts: list[dict[str, Any]] = []
    for key, label, low, high in RISK_COHORTS:
        nominals: list[float] = []
        reals: list[float] = []
        for fund in funds:
            if fund.risk_value is None or not (low <= fund.risk_value <= high):
                continue
            entry = (framed.get(fund.code) or {}).get("1y")
            if not entry or entry.get("nominal") is None:
                continue
            nominals.append(entry["nominal"])
            if entry.get("real") is not None:
                reals.append(entry["real"])
        if not nominals:
            continue
        cohorts.append(
            {
                "key": key,
                "label": label,
                "count": len(nominals),
                "median_nominal_pct": _pct_bucket(_median(nominals), 1.0),
                "median_real_pct": _pct_bucket(_median(reals), 1.0),
            }
        )
    return cohorts


async def build_funds_market_facts(fund_type: str) -> dict[str, Any] | None:
    """
    The whole fund board of one type as a quantized set of readings, or None.

    Computed across every fund of the type rather than the page the caller asked
    for. "A third of funds lost purchasing power" is a fact about the market;
    the same count over the top fifty by return would invert it.
    """
    try:
        board: FundBoard = await fetch_fund_board(fund_type)
    except (ValueError, FundDataUnavailable) as e:
        logger.info("Fund board unavailable for the market note: %s", e)
        return None

    if len(board.funds) < MIN_FUNDS:
        return None

    deflators, snapshot, fx = await _deflators()
    framed = {
        fund.code: enrich_returns(
            fund.returns,
            deflators=deflators,
            fx_series=fx,
            window_months=WINDOW_MONTHS,
        )
        for fund in board.funds
    }
    losses = summarise_real_losses(list(framed.items()), "1y")

    nominals = [
        entry["nominal"]
        for entry in (frame.get("1y") for frame in framed.values())
        if entry and entry.get("nominal") is not None
    ]
    reals = [
        entry["real"]
        for entry in (frame.get("1y") for frame in framed.values())
        if entry and entry.get("real") is not None
    ]

    if len(nominals) < MIN_MEASURED_FUNDS:
        return None

    beat_inflation = sum(1 for value in reals if value > 0)
    beat_pct = _bucket(beat_inflation / len(reals) * 100, 5.0) if reals else None

    risk_free = board.risk_free_rate
    beat_risk_free = (
        sum(1 for value in nominals if value > risk_free) if risk_free is not None else None
    )

    p10 = _pct_bucket(_percentile(reals, 0.10), 1.0)
    p90 = _pct_bucket(_percentile(reals, 0.90), 1.0)
    umbrellas = _umbrella_stats(board.funds, framed)

    return {
        "stance": classify_fund_stance(beat_pct),
        "fund_type": board.fund_type,
        "fund_type_label": board.fund_type_label,
        "stale": board.stale,
        "total": len(board.funds),
        "tradable": sum(1 for fund in board.funds if fund.tradable),
        "measured": len(nominals),
        "median_nominal_pct": _pct_bucket(_median(nominals), 1.0),
        "median_real_pct": _pct_bucket(_median(reals), 1.0),
        "spread": {
            "p10_real_pct": p10,
            "p90_real_pct": p90,
            "width_pct": (_bucket(p90 - p10, 1.0) if p10 is not None and p90 is not None else None),
            "measured": len(reals),
        },
        "inflation": {
            "beat_count": beat_inflation,
            "measured": len(reals),
            "beat_pct": beat_pct,
            "inflation_pct": _pct(snapshot.inflation_yoy) if snapshot else None,
            # Funds that printed a lira gain their holder did not keep. The one
            # figure on this board that reframes a sorted return column.
            "nominal_gain_real_loss": losses.count,
            "nominal_gain_real_loss_measured": losses.measured,
            "example": (
                {
                    "code": losses.example_key,
                    "nominal_pct": _pct_bucket(losses.example_nominal, 1.0),
                    "real_pct": _pct_bucket(losses.example_real, 1.0),
                }
                if losses.example_key
                else None
            ),
        },
        "risk_free": {
            "rate_pct": _pct(risk_free),
            "source": "money_market_median" if risk_free is not None else None,
            "beat_count": beat_risk_free,
        },
        "leaders": umbrellas[:TOP_UMBRELLAS],
        "laggards": _tail(umbrellas, TOP_UMBRELLAS),
        "risk_cohorts": _risk_cohorts(board.funds, framed),
        "deflatable_windows": sorted(w for w, value in deflators.items() if value is not None),
    }


def funds_market_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    inflation = facts["inflation"]
    spread = facts["spread"]
    risk_free = facts["risk_free"]

    board_lines = [
        f"- Universe: {facts['fund_type_label']}, {facts['total']} funds "
        f"({facts['tradable']} open to TEFAS orders)",
        f"- Funds with a measurable one-year return: {facts['measured']}",
        f"- Median one-year return, nominal: {_show_pct(facts['median_nominal_pct'])}",
    ]
    if facts["median_real_pct"] is None:
        board_lines.append(
            "- Median one-year return, real: not available — the inflation series "
            "does not cover this window, so the year cannot be read in "
            "purchasing-power terms"
        )
    else:
        board_lines.append(
            f"- Median one-year return, real: {_show_pct(facts['median_real_pct'])} "
            f"(annual CPI {_show_pct(inflation['inflation_pct'], sign=False)})"
        )

    inflation_lines = [
        f"- Funds that beat inflation over the year: {inflation['beat_count']} of "
        f"{inflation['measured']} measured "
        f"({_show_pct(inflation['beat_pct'], sign=False)})",
        f"- Funds that gained in lira and still lost purchasing power: "
        f"{inflation['nominal_gain_real_loss']} of "
        f"{inflation['nominal_gain_real_loss_measured']} measured",
    ]
    if inflation["example"]:
        example = inflation["example"]
        inflation_lines.append(
            f"- The clearest such case: {example['code']}, "
            f"{_show_pct(example['nominal_pct'])} in lira and "
            f"{_show_pct(example['real_pct'])} after inflation"
        )

    spread_lines = [
        f"- Real one-year return at the 10th percentile: {_show_pct(spread['p10_real_pct'])}",
        f"- Real one-year return at the 90th percentile: {_show_pct(spread['p90_real_pct'])}",
        f"- Gap between them: {_show_pct(spread['width_pct'], sign=False)} "
        f"across {spread['measured']} funds",
    ]

    if risk_free["rate_pct"] is None:
        risk_free_lines = [
            "- The risk-free rate could not be estimated from this board, so there "
            "is no hurdle to measure these returns against"
        ]
    else:
        risk_free_lines = [
            f"- Risk-free rate: {_show_pct(risk_free['rate_pct'], sign=False)} annual, "
            "estimated from the median return of money-market funds on this board "
            "rather than taken from the central bank's policy rate",
        ]
        if risk_free["beat_count"] is not None:
            risk_free_lines.append(
                f"- Funds whose nominal one-year return cleared that rate: "
                f"{risk_free['beat_count']} of {facts['measured']}"
            )

    def _umbrella_line(entry: dict[str, Any]) -> str:
        return (
            f"{entry['umbrella']}: median {_show_pct(entry['median_nominal_pct'])} nominal, "
            f"{_show_pct(entry['median_real_pct'])} real, across {entry['count']} funds"
        )

    cohort_lines = [
        f"TEFAS risk grade {cohort['label']}: median "
        f"{_show_pct(cohort['median_nominal_pct'])} nominal, "
        f"{_show_pct(cohort['median_real_pct'])} real, across {cohort['count']} funds"
        for cohort in facts["risk_cohorts"]
    ]

    windows = facts["deflatable_windows"]
    coverage = (
        f"Only these windows can be deflated: {', '.join(windows)}. Every other "
        "period on the board is nominal only."
        if windows
        else "No window could be deflated — the inflation series is unavailable, so "
        "every figure here is nominal."
    )

    return {
        "stance": facts["stance"].replace("_", " "),
        "board": "\n".join(board_lines),
        "inflation": "\n".join(inflation_lines),
        "spread": "\n".join(spread_lines),
        "risk_free": "\n".join(risk_free_lines),
        "leaders": _bullet([_umbrella_line(entry) for entry in facts["leaders"]]),
        "laggards": _bullet([_umbrella_line(entry) for entry in facts["laggards"]]),
        "risk_cohorts": _bullet(cohort_lines),
        "coverage": coverage,
    }


async def funds_market_note(
    facts: dict[str, Any] | None, user_id: str | None = None
) -> dict[str, Any]:
    """The note for this fund board, or `unavailable` when it cannot be read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(FUNDS_MARKET_SPEC, facts, funds_market_values(facts), user_id)
