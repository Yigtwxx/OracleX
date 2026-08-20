"""
Daily exchange flow, from the Coin Metrics Community API.

The one piece of the board that is not about how a network is running but about
what is moving across it. Kept deliberately small: real-time whale and bridge
tracking needs a labelled-address registry this app does not have, and inventing
one out of unlabelled transfers would produce a feed that looks authoritative
and is not.

**Coverage is two chains, and that is a property of the free tier, not a choice.**
The community endpoint answers 403 for `sol` and `trx` on these metrics — the
request was tried before this module was written. So the strip covers Bitcoin
and Ethereum, names its own limit, and says nothing about the other six rather
than showing them as zero.

The readings are daily, not live. `as_of` carries the day they describe, because
a 24-hour flow figure presented next to a block that landed nine seconds ago
would otherwise read as though both were current.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

from services.http_client import get_json

logger = logging.getLogger(__name__)

COINMETRICS_API = "https://community-api.coinmetrics.io/v4"
API_TIMEOUT = 10.0

# Assets the community tier actually serves these metrics for.
COVERED = {"btc": "BTC", "eth": "ETH"}

# How far back to ask.
#
# Five days was enough for the original job: metrics land at different times, so
# the newest row carrying a given metric is not necessarily the newest row
# overall, and five days guarantees a late publisher still has a value to find.
#
# Thirty is for the second job this response now does. Calling a deviation
# measured against four prior observations a baseline would be the kind of
# authoritative-looking arithmetic this module's docstring already refuses;
# twenty-nine priors is a defensible one. It costs nothing: same request, same
# 1800-second cache, and 2 assets x 30 daily rows is 60 — still inside the
# `page_size` of 100 below. Past roughly 49 days it would need pagination.
LOOKBACK_DAYS = 30

# Rows a metric needs behind it before a deviation from its median means
# anything. Below this the series is reported and deliberately not judged.
MIN_BASELINE_DAYS = 8


def _metric(row: dict[str, Any], key: str) -> Optional[float]:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


# The daily history behind the strip, kept per asset from the newest successful
# fetch. Held here rather than returned on the board because the board is a
# ten-second payload polled by every open tab, and thirty days of dailies has no
# business riding along on it thirty times a minute.
_series: dict[str, list[dict[str, Any]]] = {}


def recent_series() -> dict[str, list[dict[str, Any]]]:
    """
    Daily history per covered asset, oldest first.

    Each row is ``{date, active_addresses, transactions, net_flow_usd}`` with a
    `None` wherever that metric had not published for the day. Empty until the
    first successful fetch, and left untouched by a failed one — a stale baseline
    is worth more than no baseline, and the caller can see the dates.
    """
    return {symbol: list(rows) for symbol, rows in _series.items()}


def _newest_with(rows: list[dict[str, Any]], *keys: str) -> Optional[dict[str, Any]]:
    """The most recent row carrying every one of `keys`, or None."""
    for row in reversed(rows):
        if all(_metric(row, key) is not None for key in keys):
            return row
    return None


def _history_row(row: dict[str, Any]) -> dict[str, Any]:
    """One day of the series, with a None wherever the metric had not published."""
    inflow = _metric(row, "FlowInExUSD")
    outflow = _metric(row, "FlowOutExUSD")
    return {
        "date": (row.get("time") or "")[:10],
        "active_addresses": _metric(row, "AdrActCnt"),
        "transactions": _metric(row, "TxCnt"),
        # Same subtraction order as the strip: positive means more value moved
        # onto exchanges than off them.
        "net_flow_usd": (
            round(inflow - outflow, 2) if inflow is not None and outflow is not None else None
        ),
    }


async def fetch_flows() -> dict[str, Any]:
    """
    Yesterday's exchange in/out flow and chain activity for BTC and ETH.

    Never raises: this is one strip on a board of eight chains, and an outage
    here must not cost the board. A failure comes back as an empty asset list,
    which the UI renders as "unavailable" rather than as no flow.
    """
    start_time = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()

    try:
        payload = await get_json(
            f"{COINMETRICS_API}/timeseries/asset-metrics",
            params={
                "assets": ",".join(COVERED),
                "metrics": "AdrActCnt,TxCnt,FlowInExUSD,FlowOutExUSD",
                "frequency": "1d",
                "start_time": start_time,
                "page_size": 100,
            },
            timeout=API_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — a strip, not the board
        logger.warning("[Chains] exchange flows unavailable: %s", e)
        return {"assets": [], "as_of": None}

    # Rows arrive grouped by asset, oldest first.
    series: dict[str, list[dict[str, Any]]] = {asset: [] for asset in COVERED}
    for row in (payload or {}).get("data") or []:
        asset = row.get("asset")
        if asset in series:
            series[asset].append(row)

    assets: list[dict[str, Any]] = []
    as_of: Optional[str] = None
    history: dict[str, list[dict[str, Any]]] = {}

    for asset, rows in series.items():
        history[COVERED[asset]] = [_history_row(row) for row in rows]
        flow_row = _newest_with(rows, "FlowInExUSD", "FlowOutExUSD")
        addr_row = _newest_with(rows, "AdrActCnt")
        tx_row = _newest_with(rows, "TxCnt")

        net_flow: Optional[float] = None
        if flow_row is not None:
            # Positive means more value moved onto exchanges than off them. The
            # UI reads that sign as the bearish direction, so the subtraction
            # order is load-bearing rather than arbitrary.
            net_flow = round(
                _metric(flow_row, "FlowInExUSD") - _metric(flow_row, "FlowOutExUSD"), 2
            )
            day = (flow_row.get("time") or "")[:10]
            # The oldest day across the covered assets, so the label never
            # claims data one of them has not published yet.
            if day and (as_of is None or day < as_of):
                as_of = day

        assets.append(
            {
                "symbol": COVERED[asset],
                "net_flow_usd": net_flow,
                "active_addresses": (
                    int(_metric(addr_row, "AdrActCnt")) if addr_row is not None else None
                ),
                "transactions": int(_metric(tx_row, "TxCnt")) if tx_row is not None else None,
            }
        )

    # Replaced wholesale rather than merged: a partial response is the truth about
    # what the API is serving today, and stitching it onto older rows would build a
    # series no single fetch ever saw.
    _series.clear()
    _series.update(history)

    return {"assets": assets, "as_of": as_of}
