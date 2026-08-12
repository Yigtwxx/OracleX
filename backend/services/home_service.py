"""
Home Page Service
Fetches Funding Rates (OKX), Liquidations (background WS service), On-Chain Data
(Coin Metrics / mempool.space / public ETH RPC) and the US macro calendar.

Every upstream here is free and keyless. Binance, Blockchair and blockchain.info
were the previous sources but are unreachable from some networks (TLS handshakes
are reset), so each metric was moved to an equivalent open provider.
"""

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

import httpx

from config import settings
from services import asset_registry
from services.cache import home_cache

logger = logging.getLogger(__name__)

# ==========================================
# CONSTANTS
# ==========================================

OKX_API = "https://www.okx.com/api/v5"
COINMETRICS_API = "https://community-api.coinmetrics.io/v4"
MEMPOOL_API = "https://mempool.space/api"
ETH_RPC_PRIMARY = "https://ethereum-rpc.publicnode.com"
ETH_RPC_SECONDARY = "https://eth.llamarpc.com"

# The funding-rate widget always shows these, whatever their current rate, so the
# reference pairs never drop off the panel. Listed market-cap first as a sensible
# default; the live ranking from the registry is what actually orders them.
FUNDING_CORE_SYMBOLS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "XRP",
    "BNB",
    "SOL",
    "DOGE",
    "ADA",
    "LINK",
    "AVAX",
    "LTC",
)
# How deep to read the market-cap ranking when ordering the core block. The core
# symbols are all large caps, so the top slice of the universe covers them.
FUNDING_MARKET_CAP_LOOKUP = 50
# Any other pair joins the widget on merit past this |rate| — roughly five times
# the 0.01% baseline most perpetuals sit at.
FUNDING_EXTREME_THRESHOLD = 0.0005
FUNDING_EXTREME_LIMIT = 5
# Extreme candidates are drawn from this many of the most liquid perps. OKX also
# quotes illiquid listings whose funding swings wildly; ranking by volume first
# keeps those out of the widget.
FUNDING_SCAN_UNIVERSE = 100
# Fallback when OKX's payload doesn't let us derive the settlement period. OKX
# runs both 4h and 8h perpetuals; 8h is the more common of the two.
FUNDING_DEFAULT_INTERVAL_HOURS = 8

# TTL constants (seconds)
TTL_FUNDING = 60
TTL_LIQUIDATIONS = 10
TTL_ONCHAIN = 60
TTL_MACRO = 3600
# Short negative TTL so a rate-limited macro feed isn't hammered once per request.
TTL_MACRO_BACKOFF = 300

# How old a stale fallback may be before we stop serving it. Past these bounds
# the data is no longer a reasonable stand-in for "now", so the endpoint reports
# an outage instead of quietly handing back yesterday's numbers.
MAX_STALE_FUNDING = 15 * 60
MAX_STALE_LIQUIDATIONS = 5 * 60
MAX_STALE_ONCHAIN = 6 * 3600
MAX_STALE_MACRO = 24 * 3600


class UpstreamUnavailable(RuntimeError):
    """No live upstream data and no fallback recent enough to stand in for it."""


# faireconomy.media rate-limits unfamiliar clients aggressively.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


def _child_text(element: ET.Element, tag: str) -> str:
    """Text of a child tag, or "" when the tag is absent or empty."""
    child = element.find(tag)
    if child is None:
        return ""
    return child.text or ""


# ==========================================
# MACRO CALENDAR
# ==========================================


def _event_datetime(event: Dict) -> Optional[datetime]:
    """
    Scheduled UTC datetime of a calendar entry, or None if it cannot be read.

    The feed publishes `date` as MM-DD-YYYY and `time` as e.g. "2:00pm", already in
    UTC — confirmed against known release times, where the 8:30am ET Non-Farm
    Payrolls print arrives as "12:30pm". Entries marked "All Day" or "Tentative"
    carry no usable time, so they resolve to the end of their day and stay listed
    until that day is over.
    """
    date_str = (event.get("date") or "").strip()
    if not date_str:
        return None

    try:
        day = datetime.strptime(date_str, "%m-%d-%Y").replace(tzinfo=UTC)
    except ValueError:
        return None

    time_str = (event.get("time") or "").strip().lower().replace(" ", "")
    try:
        parsed = datetime.strptime(time_str, "%I:%M%p")
    except ValueError:
        return day + timedelta(days=1) - timedelta(seconds=1)

    return day.replace(hour=parsed.hour, minute=parsed.minute)


def _upcoming(events: List[Dict]) -> List[Dict]:
    """
    Drop entries whose scheduled time has already passed.

    The feed covers the whole calendar week, so by midweek most of it describes
    releases that have already printed. An entry we cannot place in time is kept —
    better to show it than to silently discard an event we failed to parse.
    """
    now = datetime.now(UTC)
    return [event for event in events if (dt := _event_datetime(event)) is None or dt >= now]


async def fetch_macro_calendar() -> List[Dict]:
    """
    Fetch Real-time US Economic Calendar from ForexFactory XML Feed.
    Source: https://nfs.faireconomy.media/ff_calendar_thisweek.xml
    Returns: Upcoming high/medium impact USD events.

    Filtering happens per request rather than at fetch time, so the list stays
    accurate as events pass during the cache's lifetime.
    """
    return _upcoming(await _load_macro_week())


async def _load_macro_week() -> List[Dict]:
    """The full current-week feed, cached. See `fetch_macro_calendar`."""
    # Cache for 1 hour (data is weekly/daily)
    cached = home_cache.get("macro")
    if cached is not None:
        return cached

    # A recent failure is remembered under its own key. Parking an empty list in
    # the data cache would have been indistinguishable from "no events this week".
    if home_cache.is_valid("macro_backoff"):
        stale = home_cache.get_with_fallback("macro", max_age=MAX_STALE_MACRO)
        if stale:
            return stale
        raise UpstreamUnavailable("macro calendar unavailable (backing off)")

    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
    events: List[Dict] = []

    try:
        async with httpx.AsyncClient(headers=_BROWSER_HEADERS) as client:
            response = await client.get(url, timeout=10.0)

        content_type = response.headers.get("content-type", "")
        if response.status_code != 200 or "xml" not in content_type:
            # 429 responses arrive as text/html and would blow up the parser.
            logger.warning(
                "Macro calendar unavailable: HTTP %s (%s)", response.status_code, content_type
            )
            raise ValueError("unexpected macro calendar response")

        root = ET.fromstring(response.content)

        for event in root.findall("event"):
            # Filter for USD events only
            if _child_text(event, "country") != "USD":
                continue

            # Filter for Medium/High impact to reduce noise
            impact = _child_text(event, "impact")
            if impact not in ("Medium", "High"):
                continue

            events.append(
                {
                    "title": _child_text(event, "title"),
                    "country": "USD",
                    "date": _child_text(event, "date"),  # Format: MM-DD-YYYY
                    "time": _child_text(event, "time"),  # Format: 1:30pm
                    "impact": impact,
                    "forecast": _child_text(event, "forecast"),
                    "previous": _child_text(event, "previous"),
                }
            )

        # Source order is already chronological.
        home_cache.set("macro", events, TTL_MACRO)
        return events

    except Exception as e:
        logger.error("Error fetching macro calendar: %s", e)
        # Return stale data if it is still recent enough to be meaningful.
        stale = home_cache.get_with_fallback("macro", max_age=MAX_STALE_MACRO)
        if stale:
            return stale
        # Back off briefly so a rate-limited feed isn't retried on every request,
        # but surface the outage — an empty calendar is a claim about the week,
        # not an absence of information.
        home_cache.set("macro_backoff", True, TTL_MACRO_BACKOFF)
        raise UpstreamUnavailable("macro calendar unavailable") from e


# ==========================================
# FUNDING RATES
# ==========================================


async def _okx_price_index(
    client: httpx.AsyncClient, path: str, params: Dict[str, str], price_field: str
) -> Dict[str, float]:
    """Fetch an OKX list endpoint once and index `instId → price_field`."""
    response = await client.get(f"{OKX_API}{path}", params=params)
    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != "0":
        raise ValueError(f"OKX {path} returned code {payload.get('code')}")

    prices: Dict[str, float] = {}
    for item in payload.get("data") or []:
        try:
            prices[item["instId"]] = float(item[price_field])
        except (KeyError, TypeError, ValueError):
            continue
    return prices


async def _okx_funding_rates(client: httpx.AsyncClient) -> Dict[str, Dict[str, Any]]:
    """
    Every OKX swap's current funding rate, indexed `instId → payload`.

    `instId=ANY` returns the whole board in one call, so widening the scanned
    universe costs nothing beyond this single request.
    """
    response = await client.get(
        f"{OKX_API}/public/funding-rate", params={"instId": "ANY", "instType": "SWAP"}
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != "0":
        raise ValueError(f"OKX funding-rate returned code {payload.get('code')}")

    return {item["instId"]: item for item in payload.get("data") or [] if item.get("instId")}


def _funding_interval_hours(payload: Dict[str, Any]) -> int:
    """Settlement period in hours, derived from the gap between the two funding times."""
    try:
        gap_ms = int(payload["nextFundingTime"]) - int(payload["fundingTime"])
    except (KeyError, TypeError, ValueError):
        return FUNDING_DEFAULT_INTERVAL_HOURS

    hours = round(gap_ms / 3_600_000)
    return hours if hours > 0 else FUNDING_DEFAULT_INTERVAL_HOURS


def _build_funding_row(
    symbol: str,
    payload: Dict[str, Any],
    mark_prices: Dict[str, float],
    index_prices: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    """One widget row, or None when the payload has no usable rate."""
    try:
        funding_rate = float(payload["fundingRate"])
        next_funding_time = int(payload["fundingTime"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "symbol": symbol,
        "rate": funding_rate,
        "rate_formatted": f"{funding_rate * 100:.4f}%",
        "index_price": index_prices.get(f"{symbol}-USDT"),
        "mark_price": mark_prices.get(f"{symbol}-USDT-SWAP"),
        "next_funding_time": next_funding_time,
        "interval_hours": _funding_interval_hours(payload),
        "is_extreme": abs(funding_rate) >= FUNDING_EXTREME_THRESHOLD,
    }


async def fetch_funding_rates() -> List[Dict]:
    """
    Funding rates for the core reference perpetuals, plus any liquid outlier.

    `FUNDING_CORE_SYMBOLS` leads the list in market-cap order so the panel reads
    the same way between refreshes; up to `FUNDING_EXTREME_LIMIT` other pairs
    follow when their rate clears `FUNDING_EXTREME_THRESHOLD`.

    Returns: List of {symbol, rate, rate_formatted, index_price, mark_price,
    next_funding_time, interval_hours, is_extreme}

    `index_price` / `mark_price` are None when OKX did not return that quote —
    the widget renders those as unknown rather than as a $0.00 price.
    """
    # Check cache
    cached = home_cache.get("funding")
    if cached is not None:
        return cached

    try:
        # `get_top_perp_symbols` ranks by 24h notional and drops OKX's tokenised
        # equities and commodities, which the raw funding board still carries.
        # `get_crypto_symbols` is market-cap ordered and gives the core its order.
        liquid_symbols, ranked_by_cap = await asyncio.gather(
            asset_registry.get_top_perp_symbols(FUNDING_SCAN_UNIVERSE),
            asset_registry.get_crypto_symbols(FUNDING_MARKET_CAP_LOOKUP),
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            # One call each for mark prices, index prices and the funding board.
            mark_prices, index_prices, funding_board = await asyncio.gather(
                _okx_price_index(client, "/public/mark-price", {"instType": "SWAP"}, "markPx"),
                _okx_price_index(client, "/market/index-tickers", {"quoteCcy": "USDT"}, "idxPx"),
                _okx_funding_rates(client),
                return_exceptions=True,
            )

        if isinstance(mark_prices, BaseException):
            logger.warning("[Funding] OKX mark prices failed: %s", mark_prices)
            mark_prices = {}
        if isinstance(index_prices, BaseException):
            logger.warning("[Funding] OKX index prices failed: %s", index_prices)
            index_prices = {}
        if isinstance(funding_board, BaseException):
            raise ValueError("OKX funding board unavailable") from funding_board

        def row_for(symbol: str) -> Optional[Dict[str, Any]]:
            payload = funding_board.get(f"{symbol}-USDT-SWAP")
            if not payload:
                logger.warning("[Funding] %s not quoted by OKX", symbol)
                return None
            return _build_funding_row(symbol, payload, mark_prices, index_prices)

        # Market-cap order, with anything the registry doesn't rank falling to
        # the back of the core block rather than jumping to the front.
        cap_rank = {symbol: rank for rank, symbol in enumerate(ranked_by_cap)}
        core_symbols = sorted(
            FUNDING_CORE_SYMBOLS, key=lambda symbol: cap_rank.get(symbol, len(cap_rank))
        )
        core = [row for row in (row_for(symbol) for symbol in core_symbols) if row]

        # Outliers are ranked among themselves first, so the limit keeps the most
        # intense ones rather than whichever happen to be most liquid.
        extremes = [
            row
            for row in (
                row_for(symbol) for symbol in liquid_symbols if symbol not in FUNDING_CORE_SYMBOLS
            )
            if row and row["is_extreme"]
        ]
        extremes.sort(key=lambda row: abs(row["rate"]), reverse=True)

        # The core block keeps its market-cap order; outliers trail it by intensity.
        results = core + extremes[:FUNDING_EXTREME_LIMIT]
        if not results:
            raise ValueError("no funding rates resolved")

        home_cache.set("funding", results, TTL_FUNDING)
        return results

    except Exception as e:
        logger.error("Error fetching funding rates: %s", e)
        stale = home_cache.get_with_fallback("funding", max_age=MAX_STALE_FUNDING)
        if stale:
            return stale
        raise UpstreamUnavailable("funding rates unavailable") from e


# ==========================================
# LIQUIDATIONS
# ==========================================


async def fetch_liquidations() -> List[Dict]:
    """
    Fetch recent liquidation orders from the background LiquidationService,
    which streams them from the OKX `liquidation-orders` channel.
    Returns: List of {symbol, side, quantity, price, amount_usd, time_ago}
    """
    # We lower the cache TTL for liquidations since it's a fast-moving "feed"
    cached = home_cache.get("liquidations")
    if cached is not None:
        return cached

    try:
        from services.liquidation_service import liquidation_service

        # Access the deque directly within a lock (or a copy of it)
        # We want the most recent ones first
        async with liquidation_service._lock:
            recent_liquidations = list(liquidation_service.liquidations)

        # The service appends new events to the right of the deque
        # So we reverse it to get newest first
        recent_liquidations.reverse()

        # Take the top 100 to show in the feed
        feed_data = recent_liquidations[:100]

        cleaned_data = []
        for item in feed_data:
            # "SELL" = Long Liquidated, "BUY" = Short Liquidated
            side_formatted = "Long" if item["side"] == "SELL" else "Short"

            # format symbol (e.g. BTCUSDT -> BTC)
            symbol_formatted = item["symbol"].replace("USDT", "")

            cleaned_data.append(
                {
                    "symbol": symbol_formatted,
                    "side": side_formatted,
                    "price": item["price"],
                    "amount_usd": item["amount_usd"],
                    "time_ago": _get_time_ago(item["timestamp"]),
                    "timestamp": item["timestamp"],
                }
            )

        home_cache.set("liquidations", cleaned_data, TTL_LIQUIDATIONS)
        return cleaned_data

    except Exception as e:
        logger.error("Error fetching liquidations from service: %s", e)
        # Fallback to stale cache if it is recent enough to still read as a feed.
        stale = home_cache.get_with_fallback("liquidations", max_age=MAX_STALE_LIQUIDATIONS)
        if stale:
            return stale
        raise UpstreamUnavailable("liquidation feed unavailable") from e


# ==========================================
# ON-CHAIN DATA (REAL APIs)
# ==========================================

# Optional Etherscan API key — only a third-line fallback for ETH gas.
ETHERSCAN_API_KEY = settings.ETHERSCAN_API_KEY


def _metric(row: Dict[str, Any], key: str) -> Optional[float]:
    """A metric off a Coin Metrics row, or None when the row does not carry it."""
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def _rows_with(rows: List[Dict[str, Any]], *keys: str) -> List[Dict[str, Any]]:
    """The subset of `rows` carrying every one of `keys`, oldest → newest."""
    return [row for row in rows if all(_metric(row, key) is not None for key in keys)]


async def _fetch_chain_activity(client: httpx.AsyncClient) -> Dict[str, Dict[str, Any]]:
    """
    Daily BTC and ETH chain metrics from the Coin Metrics Community API
    (free, keyless): active addresses, transaction counts and exchange flows.

    Returns `{"btc": {...}, "eth": {...}}` with `addresses`, `transactions`,
    `change_24h`, `net_flow_usd` and `flow_as_of`. A metric the API did not
    publish is None, never 0 — the widget has to be able to tell an unreported
    value from a measured zero.

    Metrics do not all land at the same time, so each is read from the newest row
    that actually carries it rather than from a single "latest" row.
    """
    start_time = (date.today() - timedelta(days=5)).isoformat()
    response = await client.get(
        f"{COINMETRICS_API}/timeseries/asset-metrics",
        params={
            "assets": "btc,eth",
            "metrics": "AdrActCnt,TxCnt,FlowInExUSD,FlowOutExUSD",
            "frequency": "1d",
            "start_time": start_time,
            "page_size": 100,
        },
        timeout=10.0,
    )
    response.raise_for_status()

    # Rows arrive grouped by asset and ordered oldest → newest.
    series: Dict[str, List[Dict[str, Any]]] = {"btc": [], "eth": []}
    for row in response.json().get("data") or []:
        asset = row.get("asset")
        if asset in series:
            series[asset].append(row)

    activity: Dict[str, Dict[str, Any]] = {}
    for asset, rows in series.items():
        addr_rows = _rows_with(rows, "AdrActCnt")
        tx_rows = _rows_with(rows, "TxCnt")
        flow_rows = _rows_with(rows, "FlowInExUSD", "FlowOutExUSD")

        addresses: Optional[int] = None
        change: Optional[float] = None
        if addr_rows:
            addresses = int(_metric(addr_rows[-1], "AdrActCnt"))
            if len(addr_rows) >= 2:
                previous = int(_metric(addr_rows[-2], "AdrActCnt"))
                if previous > 0:
                    change = round(((addresses - previous) / previous) * 100, 2)

        net_flow: Optional[float] = None
        flow_as_of: Optional[str] = None
        if flow_rows:
            latest_flow = flow_rows[-1]
            # Positive = more value moved onto exchanges than off them, i.e. a net
            # inflow. The widget reads that sign as the bearish direction.
            net_flow = round(
                _metric(latest_flow, "FlowInExUSD") - _metric(latest_flow, "FlowOutExUSD"), 2
            )
            flow_as_of = (latest_flow.get("time") or "")[:10] or None

        activity[asset] = {
            "addresses": addresses,
            "transactions": int(_metric(tx_rows[-1], "TxCnt")) if tx_rows else None,
            "change_24h": change,
            "net_flow_usd": net_flow,
            "flow_as_of": flow_as_of,
        }

    return activity


async def _fetch_btc_mempool(client: httpx.AsyncClient) -> Optional[int]:
    """BTC mempool size in virtual bytes, from mempool.space, or None if absent."""
    response = await client.get(f"{MEMPOOL_API}/mempool", timeout=8.0)
    response.raise_for_status()
    vsize = response.json().get("vsize")
    return None if vsize is None else int(vsize)


def _round_gwei(gas_gwei: float) -> float:
    """Preserve decimal precision for sub-1 Gwei (e.g. 0.04)."""
    return round(gas_gwei, 1) if gas_gwei >= 1 else round(gas_gwei, 2)


async def _rpc_gas_price(client: httpx.AsyncClient, url: str) -> float:
    """`eth_gasPrice` against a public JSON-RPC node, in Gwei."""
    response = await client.post(
        url,
        json={"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1},
        timeout=5.0,
    )
    if response.status_code != 200:
        return 0.0
    result = response.json().get("result")
    if not result:
        return 0.0
    return int(result, 16) / 1e9


async def _fetch_eth_gas(client: httpx.AsyncClient) -> Optional[float]:
    """
    ETH gas price in Gwei, or None when no source answered.

    Tries two keyless public RPC nodes before the optional Etherscan fallback, so
    the widget works without any API key configured.
    """
    for rpc_url in (ETH_RPC_PRIMARY, ETH_RPC_SECONDARY):
        try:
            gas_gwei = await _rpc_gas_price(client, rpc_url)
            if gas_gwei > 0:
                return _round_gwei(gas_gwei)
        except Exception as e:
            logger.warning("[OnChain] ETH RPC gas price error (%s): %s", rpc_url, e)

    # Fallback: Etherscan V2 (if key available)
    if ETHERSCAN_API_KEY:
        try:
            response = await client.get(
                "https://api.etherscan.io/v2/api",
                params={
                    "chainid": "1",
                    "module": "gastracker",
                    "action": "gasoracle",
                    "apikey": ETHERSCAN_API_KEY,
                },
                timeout=5.0,
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "1":
                    result = data.get("result", {})
                    gas_val = float(result.get("ProposeGasPrice", 0))
                    if gas_val > 0:
                        return gas_val
        except Exception as e:
            logger.warning("[OnChain] Etherscan gas oracle error: %s", e)

    # Every source failed. Reporting 0 here would render as "0.0 Gwei / Low cost".
    return None


_EMPTY_ACTIVITY: Dict[str, Any] = {
    "addresses": None,
    "transactions": None,
    "change_24h": None,
    "net_flow_usd": None,
    "flow_as_of": None,
}


def _stale_onchain() -> Optional[Dict[str, Any]]:
    """The last good on-chain payload, flagged as stale, if recent enough to serve."""
    stale = home_cache.get_with_fallback("onchain", max_age=MAX_STALE_ONCHAIN)
    return None if stale is None else {**stale, "stale": True}


def _unknown_onchain() -> Dict[str, Any]:
    """
    The payload shape with every reading explicitly unknown.

    Unlike the other home endpoints this one does not 503 when everything fails:
    it is a composite of four independent sources, and each field already carries
    its own "unmeasured" state that the widget renders as "—". Saying so per
    metric is more useful than failing the whole request, and it cannot be
    mistaken for a measurement the way a payload of zeros could.
    """
    return {
        "active_addresses": {
            "btc": None,
            "eth": None,
            "btc_change_24h": None,
            "eth_change_24h": None,
        },
        "transactions_24h": {"btc": None, "eth": None},
        "network_load": {"eth_gas_gwei": None, "btc_mempool_size_vbytes": None},
        "exchange_flows": {"btc_net_flow_usd": None, "eth_net_flow_usd": None, "as_of": None},
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "stale": False,
    }


async def fetch_onchain_data() -> Dict[str, Any]:
    """
    Fetch REAL on-chain data from free, keyless APIs.

    Sources:
    - Coin Metrics Community: BTC/ETH active addresses, transaction counts and
                              exchange in/out flows
    - mempool.space:          BTC mempool size
    - publicnode / llamarpc:  ETH gas price

    Any metric that could not be measured comes back as None. `as_of` is when the
    payload was built and `stale` says whether it is being replayed from cache.
    """
    cached = home_cache.get("onchain")
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient() as client:
            # Fetch all data sources in parallel
            activity, mempool_bytes, eth_gas = await asyncio.gather(
                _fetch_chain_activity(client),
                _fetch_btc_mempool(client),
                _fetch_eth_gas(client),
                return_exceptions=True,
            )

        # Handle exceptions from gather
        if isinstance(activity, BaseException):
            logger.warning("[OnChain] Chain activity exception: %s", activity)
            activity = {}
        if isinstance(mempool_bytes, BaseException):
            logger.warning("[OnChain] Mempool exception: %s", mempool_bytes)
            mempool_bytes = None
        if isinstance(eth_gas, BaseException):
            logger.warning("[OnChain] Gas exception: %s", eth_gas)
            eth_gas = None

        btc = activity.get("btc") or _EMPTY_ACTIVITY
        eth = activity.get("eth") or _EMPTY_ACTIVITY

        data = {
            "active_addresses": {
                "btc": btc["addresses"],
                "eth": eth["addresses"],
                "btc_change_24h": btc["change_24h"],
                "eth_change_24h": eth["change_24h"],
            },
            "transactions_24h": {
                "btc": btc["transactions"],
                "eth": eth["transactions"],
            },
            "network_load": {
                "eth_gas_gwei": eth_gas,
                "btc_mempool_size_vbytes": mempool_bytes,
            },
            "exchange_flows": {
                "btc_net_flow_usd": btc["net_flow_usd"],
                "eth_net_flow_usd": eth["net_flow_usd"],
                # Exchange flows settle a day behind, so the widget labels the day
                # they describe rather than implying they are live.
                "as_of": btc["flow_as_of"] or eth["flow_as_of"],
            },
            "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
            "stale": False,
        }

        measured = (
            btc["addresses"],
            eth["addresses"],
            btc["transactions"],
            eth["transactions"],
            btc["net_flow_usd"],
            eth["net_flow_usd"],
            eth_gas,
            mempool_bytes,
        )
        if not any(value is not None for value in measured):
            # Nothing resolved. Caching this would overwrite the last good payload
            # with an empty one, so prefer the existing fallback.
            logger.warning("[OnChain] No metric resolved; not caching empty payload")
            return _stale_onchain() or data

        home_cache.set("onchain", data, TTL_ONCHAIN)
        return data

    except Exception as e:
        logger.error("[OnChain] Fatal error in fetch_onchain_data: %s", e)
        return _stale_onchain() or _unknown_onchain()


def _get_time_ago(timestamp_ms: int) -> str:
    # Convert exchange timestamp (ms) to readable string
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    now = datetime.now()
    diff = now - dt

    seconds = diff.total_seconds()
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    else:
        return f"{int(seconds // 3600)}h ago"
