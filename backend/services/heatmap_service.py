"""
Heatmap board data — one row per asset, four selectable metrics.
Metrics: Price Change, Volume, Turnover, Developer Activity.

Turnover (24h volume ÷ market cap) replaced a "social hype" score. That score
was built on CoinGecko's community data, which the free tier no longer
populates — `twitter_followers` is gone and `reddit_subscribers` comes back as a
flat 0 for every coin, so the formula confidently reported zero social activity
for Bitcoin. Reddit's public JSON API now requires OAuth and the X API is paid,
so there is no free replacement for the underlying figures. Turnover measures
much the same thing — how actively an asset trades relative to its size — from
data the board already fetches, and every number in it is a real observation.

Developer scores do still come from CoinGecko, one request per coin, which is
more than the free tier absorbs for the whole board on every refresh. Those are
remembered on disk and each background refresh renews the stalest handful. A
coin not yet resolved carries `None`, which the UI renders as "no score yet" —
never a neutral-looking number, because on the board a placeholder 50 is
indistinguishable from a measured 50.

Two rules run through the whole module:

  * **A missing reading is `None`, never `0`.** The board colours `>= 0` as a
    gain, so a coerced zero renders as a green "+0.0%" tile — a confident claim
    built out of an absence. Every metric here reports its own unknown.

  * **Nothing slow happens inside a request.** The per-coin detail rotation is
    paced against CoinGecko's rate limit and takes tens of seconds, so it lives
    in `refresh_heatmap()`, which the scheduler calls. Readers get whatever the
    last refresh produced, or a stale copy with `stale=True` on it.
"""

import asyncio
import logging
import math
import os
import time
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Tuple

import httpx

from config import settings
from services import asset_registry, coingecko
from services.cache import market_cache

logger = logging.getLogger(__name__)

# ── Board shape ─────────────────────────────────────────────────────────────
# How many assets the board covers. Which ones is resolved live from the
# market-cap ranking, so a newly launched token appears on its own.
HEATMAP_COIN_COUNT = settings.HEATMAP_COIN_COUNT

# CoinGecko's ceiling for /coins/markets. Asking for more silently truncates.
MARKETS_PAGE_SIZE = 250

# ── Refresh budget ──────────────────────────────────────────────────────────
# Per-coin detail calls issued on each background refresh (developer scores and
# sectors). CoinGecko's anonymous tier starts returning 429 well before ten
# back-to-back requests; a demo key raises that ceiling. The disk cache carries
# the rest, so the whole board is covered within a few refresh cycles.
DETAIL_FETCH_LIMIT_ANONYMOUS = 4
DETAIL_FETCH_LIMIT_WITH_KEY = 10

# Spacing between those per-coin calls, again to stay under the rate limit.
DETAIL_FETCH_DELAY_SECONDS = 2.5

# How long a stored developer score stays fresh. Repo activity moves over weeks.
METRICS_TTL_SECONDS = 6 * 3600

# Sectors get their own, far longer TTL. An asset's category does not change
# from one day to the next, and re-deriving a stable classification would spend
# the same rate-limit budget the unresolved coins are waiting for.
SECTORS_TTL_SECONDS = 30 * 86400

# A coin whose detail request fails is retried on an exponential backoff rather
# than immediately. Without this, four permanently-failing ids sit at the front
# of the rotation forever — they always look "unresolved" — and no other coin on
# the board ever gets its turn.
FAILURE_BACKOFF_BASE_SECONDS = 900
FAILURE_BACKOFF_MAX_SECONDS = 86400

# Bumped whenever the scoring formula changes. Stored scores carrying an older
# version are recomputed regardless of TTL, so a fix does not sit behind days of
# disk cache written by the previous formula.
SCORE_VERSION = 3

# ── Cache ───────────────────────────────────────────────────────────────────
HEATMAP_CACHE_KEY = "heatmap"
HEATMAP_TTL_SECONDS = 300
# Past this, a stale board stops being "the market a few minutes ago" and starts
# being a misleading picture. The endpoint reports unavailable instead.
HEATMAP_STALE_MAX_AGE_SECONDS = 3600

# ── Disk cache ──────────────────────────────────────────────────────────────
# Absolute, so the store does not fork in two depending on where the process was
# launched from. See asset_registry.REGISTRY_DIR.
COIN_SECTORS_FILE = os.path.join(asset_registry.REGISTRY_DIR, "coin_sectors.json")
COIN_METRICS_FILE = os.path.join(asset_registry.REGISTRY_DIR, "coin_metrics.json")

# ── Taxonomy ────────────────────────────────────────────────────────────────
# CoinGecko category → display sector. Keyed on CoinGecko's *category* taxonomy
# rather than on individual coins, so it stays correct as new assets launch:
# a new layer-1 gets tagged "Smart Contract Platform" upstream and lands in
# "Smart Contracts" here without any edit.
#
# Order matters. CoinGecko tags almost every chain "Smart Contract Platform" and
# "Layer 1 (L1)" — Bitcoin and XRP included — so those broad labels sit last and
# only apply once no more distinctive category has matched. A test pins this
# ordering, because reordering the list silently reclassifies the whole board.
CATEGORY_TO_SECTOR: List[Tuple[str, str]] = [
    ("meme", "Meme"),
    ("layer 2", "Layer 2"),
    ("rollup", "Layer 2"),
    ("oracle", "Oracle"),
    ("liquid staking", "Liquid Staking"),
    ("decentralized finance", "DeFi"),
    ("decentralized exchange", "DeFi"),
    ("lending", "DeFi"),
    ("yield", "DeFi"),
    ("centralized exchange", "Exchange"),
    ("exchange-based token", "Exchange"),
    ("artificial intelligence", "AI/Compute"),
    ("depin", "AI/Compute"),
    ("gaming", "Gaming"),
    ("metaverse", "Gaming"),
    ("nft", "NFT"),
    ("storage", "Storage"),
    ("privacy", "Privacy"),
    ("interoperability", "Interoperability"),
    ("bridge", "Interoperability"),
    ("payment", "Payments"),
    ("stablecoin", "Stablecoin"),
    ("real world assets", "RWA"),
    ("tokenized", "RWA"),
    ("infrastructure", "Infrastructure"),
    ("proof of work", "Proof of Work"),
    ("smart contract platform", "Smart Contracts"),
    ("layer 1", "Smart Contracts"),
]

# Sector shown for a coin whose detail request has not succeeded yet. Kept
# distinct from "Other" (resolved, matched nothing) so the board can say which
# it is instead of implying a classification it never made.
UNCLASSIFIED_SECTOR = "Unclassified"

PEG_STABLECOIN = "stablecoin"
PEG_WRAPPED = "wrapped"

# Category substrings that mark an asset as tracking something else's price
# rather than finding its own. Checked before the sector table: a wrapped BTC is
# more usefully described as wrapped than as whatever sector its categories
# happen to also mention.
PEG_CATEGORY_SIGNALS: List[Tuple[str, str]] = [
    ("stablecoin", PEG_STABLECOIN),
    ("eur stablecoin", PEG_STABLECOIN),
    ("wrapped", PEG_WRAPPED),
    ("liquid staking", PEG_WRAPPED),
    ("liquid restaking", PEG_WRAPPED),
    ("tokenized btc", PEG_WRAPPED),
    ("bridged", PEG_WRAPPED),
]

# Fallback for coins whose categories have not been fetched yet. Categories are
# the real source — this exists only so the top of the board is not full of flat
# ~0.00% tiles during the first few refresh cycles of a cold start.
WRAPPED_BASES = frozenset(
    {
        "WBTC",
        "WETH",
        "WBNB",
        "WSOL",
        "STETH",
        "WSTETH",
        "WEETH",
        "RETH",
        "WBETH",
        "CBBTC",
        "LBTC",
        "SOLVBTC",
        "BSC-USD",
    }
)

# Scaling denominators for the developer score. Both are log-scaled: the linear
# formula they replaced summed three capped terms, so every project past ~50k
# stars pinned at exactly 100 whether or not anyone had committed in a month.
_ACTIVITY_LOG_SCALE = math.log10(1001)  # 1000 commits/4w reaches the top
_REACH_LOG_SCALE = math.log10(100_001)  # 100k stars reaches the top

# Volume score anchors, in log10(USD). $1M scores 0, $100B scores 100 — so a
# $2B coin and a $200M coin are visibly different, which the previous linear
# formula could not express: it saturated at $10B and left everything under $2B
# in the same unpainted bucket as "no data".
_VOLUME_LOG_FLOOR = 6.0  # $1M
_VOLUME_LOG_SPAN = 5.0  # five decades to $100B

# Guards the refresh path so N concurrent cold-cache readers issue one upstream
# fetch between them rather than N.
#
# Built on first use, not at import: on Python 3.9 an asyncio.Lock() binds to
# whatever loop is current when it is constructed, and at import time that is
# not the loop the server ends up running on. The loop it bound to is remembered
# so a second loop in the same process — a lifespan restart, or one test after
# another — gets its own lock instead of awaiting a future from a dead one.
_refresh_lock: Optional[asyncio.Lock] = None
_refresh_lock_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_lock() -> asyncio.Lock:
    global _refresh_lock, _refresh_lock_loop
    loop = asyncio.get_running_loop()
    if _refresh_lock is None or _refresh_lock_loop is not loop:
        _refresh_lock = asyncio.Lock()
        _refresh_lock_loop = loop
    return _refresh_lock


def _detail_fetch_limit() -> int:
    """How many per-coin detail calls one refresh may spend."""
    return DETAIL_FETCH_LIMIT_WITH_KEY if coingecko.has_key() else DETAIL_FETCH_LIMIT_ANONYMOUS


# ═══════════════════════════════════════════════════════════════════════════
# Pure scoring and classification
# ═══════════════════════════════════════════════════════════════════════════


def _as_number(value: Any) -> Optional[float]:
    """A finite float, or None. Booleans are not numbers here."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _volume_score(volume: Optional[float]) -> Optional[float]:
    """
    24h volume on a 0-100 log scale: $1M → 0, $1B → 60, $100B → 100.

    Absolute rather than relative to the rest of the board, so a coin's colour
    does not shift because an unrelated asset entered or left the ranking, and
    the legend can name real dollar figures instead of "top quartile of these
    fifty". Unknown volume stays unknown; a genuine zero scores zero.
    """
    volume = _as_number(volume)
    if volume is None:
        return None
    scaled = (math.log10(max(volume, 1.0)) - _VOLUME_LOG_FLOOR) / _VOLUME_LOG_SPAN
    return round(max(0.0, min(1.0, scaled)) * 100, 1)


def _turnover_pct(volume: Optional[float], market_cap: Optional[float]) -> Optional[float]:
    """
    What share of the asset's market cap changed hands in 24h.

    None when either input is missing, so it is never a 0% that actually means
    "we don't know".
    """
    volume = _as_number(volume)
    market_cap = _as_number(market_cap)
    if volume is None or not market_cap or market_cap <= 0:
        return None
    return round(volume / market_cap * 100, 2)


def _score_developer(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise CoinGecko developer data into a 0-100 score.

    Two terms, deliberately separate. *Activity* is commits in the last four
    weeks — what the project is doing now. *Reach* is stars — how much attention
    it has accumulated, which is a different claim and moves on a different
    timescale. Forks are left out: they track stars closely enough that
    including both counted popularity twice against a single activity term.

    Both are log-scaled. The linear formula this replaced capped at 100, so
    every well-known repository scored exactly 100 regardless of whether it had
    seen a commit in a month, and the metric was a constant across the top of
    the board.
    """
    scored: Dict[str, Any] = {"fetched_at": time.time(), "score_version": SCORE_VERSION}

    developer = data.get("developer_data") or {}
    commits_4w = _as_number(developer.get("commit_count_4_weeks")) or 0.0
    stars = _as_number(developer.get("stars")) or 0.0
    forks = _as_number(developer.get("forks")) or 0.0

    # A coin with no public repo genuinely has no developer activity to report,
    # which is different from having a repo that scores zero. No score key is
    # written, so the caller reports it as unknown.
    if not (stars or forks or commits_4w):
        return scored

    activity = min(1.0, math.log10(1 + max(commits_4w, 0.0)) / _ACTIVITY_LOG_SCALE)
    reach = min(1.0, math.log10(1 + max(stars, 0.0)) / _REACH_LOG_SCALE)

    scored["developer_score"] = round(100 * (0.60 * activity + 0.40 * reach), 1)
    scored["github_commits"] = commits_4w
    scored["github_stars"] = stars
    return scored


def _derive_sector(categories: Optional[List[str]]) -> Optional[str]:
    """
    Map a coin's CoinGecko categories onto a display sector.

    None means the categories are not known yet — the detail request has not
    succeeded. "Other" means they are known and matched nothing. Collapsing
    those two into one label is what made the sector view unreadable: half of
    "Other" was a classification and half was an absence.
    """
    lowered = [c.lower() for c in (categories or []) if c]
    if not lowered:
        return None
    for keyword, sector in CATEGORY_TO_SECTOR:
        if any(keyword in category for category in lowered):
            return sector
    return "Other"


def _classify_peg(symbol: str, categories: Optional[List[str]]) -> Optional[str]:
    """
    Whether the asset tracks another price: "stablecoin", "wrapped", or None.

    Category-driven, so it keeps working as new tokens launch. The symbol sets
    are only consulted while a coin's categories are still unresolved — without
    them a cold start puts USDT, USDC and WBTC among the largest tiles on the
    board, each reading a flat ~0.00%.
    """
    lowered = [c.lower() for c in (categories or []) if c]
    for keyword, peg_type in PEG_CATEGORY_SIGNALS:
        if any(keyword in category for category in lowered):
            return peg_type

    if lowered:
        # Categories were resolved and said nothing about a peg. Trust that
        # over a symbol lookup, which cannot tell WETH from a token that merely
        # starts with a W.
        return None

    upper = (symbol or "").upper()
    if upper in asset_registry.STABLECOIN_BASES:
        return PEG_STABLECOIN
    if upper in WRAPPED_BASES:
        return PEG_WRAPPED
    return None


def _weighted_change(coins: List[Dict[str, Any]], field: str) -> Optional[float]:
    """
    Market-cap-weighted mean of `field`, or None when nothing can be measured.

    The unweighted mean this replaced let a $300M token move a sector average as
    much as a $2T one, and that figure reached the generated report as if it
    were the sector's return. Coins with no reading are left out entirely rather
    than folded in as zeroes.
    """
    total_cap = 0.0
    accumulated = 0.0
    for coin in coins:
        value = _as_number(coin.get(field))
        market_cap = _as_number(coin.get("market_cap")) or 0.0
        if value is None or market_cap <= 0:
            continue
        accumulated += market_cap * value
        total_cap += market_cap
    if total_cap <= 0:
        return None
    return round(accumulated / total_cap, 2)


def _mean_change(coins: List[Dict[str, Any]], field: str) -> Optional[float]:
    """Unweighted mean, kept only for the report's legacy sector column."""
    values = [v for v in (_as_number(c.get(field)) for c in coins) if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


# ═══════════════════════════════════════════════════════════════════════════
# Board assembly (pure)
# ═══════════════════════════════════════════════════════════════════════════


def _build_coins(
    market_rows: List[Dict[str, Any]], details: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """One board row per market row, ranked by market cap. No I/O."""
    coins: List[Dict[str, Any]] = []
    for row in market_rows or []:
        coin_id = row.get("id") or ""
        symbol = (row.get("symbol") or "").upper()
        detail = details.get(coin_id) or {}

        volume = _as_number(row.get("total_volume"))
        market_cap = _as_number(row.get("market_cap")) or 0.0

        coins.append(
            {
                "id": coin_id,
                "symbol": symbol,
                "name": row.get("name") or symbol,
                "image": row.get("image") or "",
                "sector": detail.get("sector"),
                "peg_type": detail.get("peg_type"),
                "price": _as_number(row.get("current_price")),
                "market_cap": market_cap,
                "volume_24h": volume,
                "price_change_24h": _as_number(row.get("price_change_percentage_24h")),
                "price_change_7d": _as_number(row.get("price_change_percentage_7d_in_currency")),
                "developer_score": _as_number(detail.get("developer_score")),
                "volume_score": _volume_score(volume),
                "turnover_pct": _turnover_pct(volume, market_cap),
            }
        )

    coins.sort(key=lambda c: c.get("market_cap") or 0.0, reverse=True)
    return coins


def _group_sectors(coins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Market-cap-weighted sector aggregates, heaviest sector first."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for coin in coins:
        grouped.setdefault(coin.get("sector") or UNCLASSIFIED_SECTOR, []).append(coin)

    sectors: List[Dict[str, Any]] = []
    for sector, members in grouped.items():
        measured = sum(1 for c in members if _as_number(c.get("price_change_24h")) is not None)
        sectors.append(
            {
                "sector": sector,
                "coin_count": len(members),
                "market_cap": sum(_as_number(c.get("market_cap")) or 0.0 for c in members),
                "weighted_change_24h": _weighted_change(members, "price_change_24h"),
                "weighted_change_7d": _weighted_change(members, "price_change_7d"),
                # Kept so the generated report's existing column keeps rendering
                # while it migrates to the weighted figure.
                "avg_change_24h": _mean_change(members, "price_change_24h"),
                "coverage": round(measured / len(members), 2) if members else 0.0,
                "coins": members,
            }
        )

    sectors.sort(key=lambda s: s["market_cap"], reverse=True)
    return sectors


def _shape_board(
    coins: List[Dict[str, Any]],
    *,
    limit: Optional[int] = None,
    include_pegged: bool = False,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Filter, rank and aggregate an already-built coin list into a response.

    Pure and cheap, so the cache can hold one unfiltered board and every
    parameter combination is served from it rather than triggering its own
    upstream fetch.
    """
    selected = coins if include_pegged else [c for c in coins if not c.get("peg_type")]
    excluded_pegged = len(coins) - len(selected)

    if limit is not None and limit > 0:
        selected = selected[:limit]

    return {
        "coins": selected,
        "sectors": _group_sectors(selected),
        "total_market_cap": sum(_as_number(c.get("market_cap")) or 0.0 for c in selected),
        "weighted_change_24h": _weighted_change(selected, "price_change_24h"),
        "weighted_change_7d": _weighted_change(selected, "price_change_7d"),
        "excluded_pegged": excluded_pegged,
        "unresolved_count": sum(1 for c in selected if c.get("sector") is None),
        "timestamp": generated_at or _now_iso(),
        "stale": False,
        "age_seconds": None,
    }


def _build_board(
    market_rows: List[Dict[str, Any]],
    details: Dict[str, Dict[str, Any]],
    *,
    limit: Optional[int] = None,
    include_pegged: bool = False,
) -> Dict[str, Any]:
    """`_build_coins` + `_shape_board`. The seam the tests drive."""
    return _shape_board(
        _build_coins(market_rows, details),
        limit=limit,
        include_pegged=include_pegged,
    )


def _now_iso() -> str:
    """Timezone-aware, so a client can tell how old a payload actually is."""
    return datetime.now(UTC).isoformat()


# ═══════════════════════════════════════════════════════════════════════════
# Stored per-coin details
# ═══════════════════════════════════════════════════════════════════════════


def _valid_scores(stored: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Drop scores written by an earlier formula, keeping failure bookkeeping.

    An out-of-date score is not served while it waits its turn in the rotation —
    those coins count as unresolved, which puts them at the front of it. The
    backoff state survives, so a coin that has been failing does not get four
    immediate retries every time the formula version changes.
    """
    valid: Dict[str, Dict[str, Any]] = {}
    for coin_id, entry in (stored or {}).items():
        if not isinstance(entry, dict):
            continue
        if entry.get("score_version") == SCORE_VERSION:
            valid[coin_id] = entry
            continue
        failure = {k: entry[k] for k in ("failed_at", "failure_count") if k in entry}
        if failure:
            valid[coin_id] = failure
    return valid


def _normalise_sectors(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Read the sector store, upgrading the pre-peg format.

    Entries used to be a bare sector string with no timestamp, which left them
    with no TTL of their own. Those are read as resolved-but-undated so they are
    refreshed once and then carry a `fetched_at` like everything else.
    """
    sectors: Dict[str, Dict[str, Any]] = {}
    for coin_id, entry in (raw or {}).items():
        if isinstance(entry, dict):
            sectors[coin_id] = entry
        elif isinstance(entry, str):
            sectors[coin_id] = {"sector": entry, "peg_type": None, "fetched_at": None}
    return sectors


def _in_backoff(entry: Dict[str, Any], now: float) -> bool:
    """Whether a previously failing coin is still inside its retry window."""
    failed_at = _as_number(entry.get("failed_at"))
    if failed_at is None:
        return False
    count = int(_as_number(entry.get("failure_count")) or 1)
    delay = min(
        FAILURE_BACKOFF_BASE_SECONDS * (2 ** max(count - 1, 0)),
        FAILURE_BACKOFF_MAX_SECONDS,
    )
    return now < failed_at + delay


def _select_refresh_targets(
    coin_ids: List[str],
    stored: Dict[str, Dict[str, Any]],
    sectors: Dict[str, Dict[str, Any]],
    *,
    now: Optional[float] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """
    Pick which coins get a detail request this round.

    Coins with nothing stored come first — they are the ones currently showing
    no score at all — then the ones whose stored reading is oldest. Rotating
    this way means the whole board reaches real data within a few refreshes
    instead of the first handful being renewed forever while the rest stay
    blank. Coins inside their failure backoff are skipped entirely; without
    that, a permanently 404ing id looks unresolved forever and holds a slot at
    the front of every round.
    """
    now = time.time() if now is None else now
    limit = _detail_fetch_limit() if limit is None else limit

    candidates: List[Tuple[int, float, str]] = []
    for coin_id in coin_ids:
        score_entry = stored.get(coin_id) or {}
        if _in_backoff(score_entry, now):
            continue

        score_at = _as_number(score_entry.get("fetched_at"))
        sector_at = _as_number((sectors.get(coin_id) or {}).get("fetched_at"))
        has_sector = coin_id in sectors

        unresolved = score_at is None or not has_sector
        stale = (score_at is not None and now - score_at > METRICS_TTL_SECONDS) or (
            has_sector and (sector_at is None or now - sector_at > SECTORS_TTL_SECONDS)
        )
        if not unresolved and not stale:
            continue

        timestamps = [t for t in (score_at, sector_at) if t is not None]
        candidates.append((0 if unresolved else 1, min(timestamps, default=0.0), coin_id))

    candidates.sort(key=lambda c: (c[0], c[1]))
    return [coin_id for _, _, coin_id in candidates[:limit]]


def _symbols_by_id(market_rows: List[Dict[str, Any]]) -> Dict[str, str]:
    return {
        row["id"]: (row.get("symbol") or "").upper() for row in market_rows or [] if row.get("id")
    }


def _merge_details(
    coin_ids: List[str],
    sectors: Dict[str, Dict[str, Any]],
    stored: Dict[str, Dict[str, Any]],
    symbols: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Fold the two disk stores into the per-coin detail the board reads."""
    details: Dict[str, Dict[str, Any]] = {}
    for coin_id in coin_ids:
        sector_entry = sectors.get(coin_id) or {}
        peg_type = sector_entry.get("peg_type")

        # `fetched_at` marks an entry this version wrote, and only those carry a
        # trustworthy peg verdict. A missing one means either nothing is stored
        # yet or the entry predates peg classification entirely — in both cases
        # the symbol sets are what stand between a cold start and USDT holding
        # one of the largest tiles on the board while reading a flat 0.00%.
        if peg_type is None and sector_entry.get("fetched_at") is None:
            peg_type = _classify_peg(symbols.get(coin_id, ""), None)

        entry: Dict[str, Any] = {
            "sector": sector_entry.get("sector"),
            "peg_type": peg_type,
        }

        score_entry = stored.get(coin_id) or {}
        if "developer_score" in score_entry:
            entry["developer_score"] = score_entry["developer_score"]
        details[coin_id] = entry
    return details


def _load_details(
    coin_ids: List[str], market_rows: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Read-only detail lookup — no upstream requests, safe inside a request."""
    return _merge_details(
        coin_ids,
        _normalise_sectors(asset_registry.read_json_cache(COIN_SECTORS_FILE) or {}),
        _valid_scores(asset_registry.read_json_cache(COIN_METRICS_FILE) or {}),
        _symbols_by_id(market_rows),
    )


async def _refresh_details(
    coin_ids: List[str], market_rows: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """
    Renew a few coins' developer scores and sectors, then return every coin's.

    Paced against CoinGecko's rate limit, which is why only `refresh_heatmap`
    calls this: at 2.5 seconds between requests a full round takes tens of
    seconds, and running it inside a request meant the regime snapshot's five
    second feed timeout cancelled it mid-sleep — spending the rate-limit budget
    and then discarding the results before they were written to disk.
    """
    sectors = _normalise_sectors(asset_registry.read_json_cache(COIN_SECTORS_FILE) or {})
    stored = _valid_scores(asset_registry.read_json_cache(COIN_METRICS_FILE) or {})
    symbols = _symbols_by_id(market_rows)

    targets = _select_refresh_targets(coin_ids, stored, sectors)
    if targets:
        logger.debug("Heatmap: refreshing details for %s", ", ".join(targets))

    for index, coin_id in enumerate(targets):
        if index:
            await asyncio.sleep(DETAIL_FETCH_DELAY_SECONDS)
        try:
            data = await coingecko.get_json(
                f"/coins/{coin_id}",
                params={
                    "localization": False,
                    "tickers": False,
                    "market_data": False,
                    "community_data": False,
                    "developer_data": True,
                    "sparkline": False,
                },
            )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                # Rate limited: the rest of this round would fail too, and the
                # coins skipped here are first in line next refresh. Not counted
                # as a failure of this coin — nothing is wrong with it.
                logger.info("CoinGecko rate limit hit — deferring remaining coins.")
                break
            logger.warning("CoinGecko detail for %s returned %s", coin_id, status)
            stored[coin_id] = _record_failure(stored.get(coin_id))
            continue
        except Exception as e:
            # The previously stored score, if any, stays untouched and keeps
            # being served — it was a real measurement.
            logger.warning("Error fetching details for %s: %s", coin_id, e)
            stored[coin_id] = _record_failure(stored.get(coin_id))
            continue

        categories = data.get("categories") or []
        stored[coin_id] = _score_developer(data)
        sectors[coin_id] = {
            "sector": _derive_sector(categories),
            "peg_type": _classify_peg(symbols.get(coin_id, ""), categories),
            "fetched_at": time.time(),
        }

    asset_registry.write_json_cache(COIN_SECTORS_FILE, sectors)
    asset_registry.write_json_cache(COIN_METRICS_FILE, stored)

    unresolved = sum(1 for coin_id in coin_ids if coin_id not in sectors)
    if unresolved:
        logger.info(
            "Heatmap: %s of %s coins have no sector or developer score yet.",
            unresolved,
            len(coin_ids),
        )

    return _merge_details(coin_ids, sectors, stored, symbols)


def _record_failure(entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Stamp a failed detail fetch so the coin backs off instead of retrying."""
    updated = dict(entry or {})
    updated["failed_at"] = time.time()
    updated["failure_count"] = int(_as_number(updated.get("failure_count")) or 0) + 1
    return updated


# ═══════════════════════════════════════════════════════════════════════════
# Upstream
# ═══════════════════════════════════════════════════════════════════════════


async def _fetch_market_rows(coin_ids: List[str]) -> List[Dict[str, Any]]:
    """The one bulk call the board needs: price, cap, volume and 24h/7d moves."""
    if not coin_ids:
        return []
    if len(coin_ids) > MARKETS_PAGE_SIZE:
        # Silently truncating would show a board that claims to be the top N and
        # is not. Cap explicitly and say so.
        logger.warning(
            "Heatmap: %s ids requested, CoinGecko returns at most %s per page.",
            len(coin_ids),
            MARKETS_PAGE_SIZE,
        )
        coin_ids = coin_ids[:MARKETS_PAGE_SIZE]

    rows = await coingecko.get_json(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "ids": ",".join(coin_ids),
            "order": "market_cap_desc",
            "per_page": MARKETS_PAGE_SIZE,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h,7d",
        },
        timeout=20.0,
    )
    return rows if isinstance(rows, list) else []


async def _universe_ids(count: int) -> List[str]:
    """Top coin ids by market cap, resolved live — no fixed list to maintain."""
    universe = await asset_registry.get_crypto_universe(count)
    return [coin["id"] for coin in universe if coin.get("id")]


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


async def refresh_heatmap() -> Optional[Dict[str, Any]]:
    """
    Rebuild the board from scratch, including the paced detail rotation.

    The scheduler's job and the startup warm-up call this. It is the only
    caller of `_refresh_details`, so no HTTP request ever waits on it.
    """
    try:
        # Ask for more than the board shows: pegged assets are resolved and then
        # filtered out, so a board of 50 needs headroom to still be 50 real
        # movers once the stablecoins are removed.
        coin_ids = await _universe_ids(min(HEATMAP_COIN_COUNT + 25, MARKETS_PAGE_SIZE))
        market_rows = await _fetch_market_rows(coin_ids)
        if not market_rows:
            logger.warning("Heatmap refresh: CoinGecko returned no market rows.")
            return None

        details = await _refresh_details(coin_ids, market_rows)
        coins = _build_coins(market_rows, details)
        _store_coins(coins)
        logger.info("Heatmap refreshed: %s assets.", len(coins))
        return _shape_board(coins, limit=HEATMAP_COIN_COUNT)
    except Exception as e:
        logger.warning("Heatmap refresh failed: %s", e)
        return None


def _store_coins(coins: List[Dict[str, Any]]) -> None:
    market_cache.set(
        HEATMAP_CACHE_KEY,
        {"coins": coins, "generated_at": _now_iso()},
        ttl=HEATMAP_TTL_SECONDS,
    )


async def _build_fresh_coins() -> Optional[List[Dict[str, Any]]]:
    """Markets call only, details straight off disk. Fast enough for a request."""
    coin_ids = await _universe_ids(min(HEATMAP_COIN_COUNT + 25, MARKETS_PAGE_SIZE))
    market_rows = await _fetch_market_rows(coin_ids)
    if not market_rows:
        return None
    return _build_coins(market_rows, _load_details(coin_ids, market_rows))


async def fetch_heatmap_data(
    limit: Optional[int] = None,
    include_pegged: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    The board, or None when it genuinely cannot be produced.

    Returning an empty board was the previous behaviour and the worst available
    one: the UI rendered a plausible-looking blank grid and the snapshot
    builder could not tell it apart from a market where nothing moved. None
    becomes a 503 at the router and reads as "unavailable" to `_safe`.

    A stale copy is preferred over nothing — up to an hour old, marked
    `stale=True` with its age — because a board from four minutes ago is a far
    better answer to "what is the market doing" than an error page.
    """
    limit = HEATMAP_COIN_COUNT if limit is None else limit

    cached = market_cache.get(HEATMAP_CACHE_KEY)
    if cached:
        return _from_cache(cached, limit, include_pegged)

    async with _get_lock():
        # Another caller may have filled it while this one waited on the lock.
        cached = market_cache.get(HEATMAP_CACHE_KEY)
        if cached:
            return _from_cache(cached, limit, include_pegged)

        try:
            coins = await _build_fresh_coins()
        except Exception as e:
            logger.warning("Heatmap fetch failed: %s", e)
            coins = None

        if coins:
            _store_coins(coins)
            return _shape_board(coins, limit=limit, include_pegged=include_pegged)

    stale = market_cache.get_with_fallback(HEATMAP_CACHE_KEY, max_age=HEATMAP_STALE_MAX_AGE_SECONDS)
    if not stale:
        return None

    board = _from_cache(stale, limit, include_pegged)
    age = market_cache.get_fallback_age(HEATMAP_CACHE_KEY)
    board["stale"] = True
    board["age_seconds"] = round(age, 1) if age is not None else None
    logger.info("Heatmap: serving a stale board (%.0fs old).", age or 0)
    return board


def _from_cache(entry: Dict[str, Any], limit: int, include_pegged: bool) -> Dict[str, Any]:
    return _shape_board(
        entry.get("coins") or [],
        limit=limit,
        include_pegged=include_pegged,
        generated_at=entry.get("generated_at"),
    )
