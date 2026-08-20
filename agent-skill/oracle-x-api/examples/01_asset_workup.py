#!/usr/bin/env python3
"""A complete read on one asset, in one pass.

"What's going on with ETH" is four questions wearing one coat: where is price,
where are the levels, where is leverage stacked, and has this configuration
resolved before. Each is a separate endpoint and none depends on another, so
they go out together — the workup costs one round trip, not four.

    python 01_asset_workup.py ETHUSDT
    python 01_asset_workup.py AAPL
"""

from __future__ import annotations

import concurrent.futures
import sys
from collections.abc import Callable
from typing import Any

import httpx
from client import BASE_URL, DEFAULT_TIMEOUT, NotFound, OracleXError, get


def is_equity(symbol: str) -> bool:
    """Equities are plain tickers; crypto pairs carry a quote or a venue prefix.

    The backend makes the same judgement before choosing an upstream — an
    unprefixed ticker used to be forced down the crypto path and read off a
    tokenised-equity market instead of the exchange it actually trades on.
    """
    upper = symbol.upper()
    if ":" in upper:
        return False
    return not upper.endswith(("USDT", "USDC", "USD", "BTC", "ETH"))


def workup(symbol: str) -> dict[str, Any]:
    """Fetch every independent view of one symbol concurrently."""
    calls: dict[str, Callable[[httpx.Client], Any]] = {
        "detail": lambda c: get(f"/api/asset-detail/{symbol}", client=c),
        "technical": lambda c: get(f"/api/technical/{symbol}", client=c),
        "memory": lambda c: get(f"/api/rag/insights/{symbol}", client=c),
    }
    if is_equity(symbol):
        calls["ownership"] = lambda c: get(f"/api/ownership/assets/{symbol}", client=c)
    else:
        calls["liquidations"] = lambda c: get(
            f"/api/liquidations/levels/{symbol}", client=c
        )

    results: dict[str, Any] = {}
    with (
        httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT) as shared,
        concurrent.futures.ThreadPoolExecutor(max_workers=len(calls)) as pool,
    ):
        futures = {pool.submit(fn, shared): name for name, fn in calls.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except NotFound:
                # A 404 is an answer: this instance holds nothing for that
                # view. Record the absence instead of dropping the key, so
                # the caller can say so rather than staying silent.
                results[name] = None
            except OracleXError as exc:
                results[name] = {"error": str(exc)}
    return results


def summarize(symbol: str, data: dict[str, Any]) -> str:
    lines = [f"# {symbol}", ""]

    detail = data.get("detail")
    if isinstance(detail, dict):
        price = detail.get("price") or detail.get("current_price")
        change = detail.get("change_24h") or detail.get("price_change_24h")
        lines.append(f"Price: {price}  ({change}% 24h)" if price else "Price: n/a")

    technical = data.get("technical")
    if technical is None:
        lines.append("Technicals: the instance could not compute levels here.")
    elif isinstance(technical, dict):
        lines.append("")
        lines.append("## Levels")
        for zone in (technical.get("zones") or [])[:6]:
            kind = zone.get("type", "?")
            low, high = zone.get("low"), zone.get("high")
            confirmed = ", ".join(zone.get("timeframes", [])) or "?"
            lines.append(
                f"- {kind}: {low}–{high} (confirmed on {confirmed}, "
                f"strength {zone.get('strength', '?')})"
            )

    if data.get("liquidations"):
        lines += ["", "## Leverage", "Liquidation levels retrieved — see raw payload."]
    if data.get("ownership"):
        lines += ["", "## Holders", "Institutional positions retrieved."]

    memory = data.get("memory")
    if memory:
        lines += ["", "## Precedent", "The store holds prior context for this symbol."]
    else:
        lines += ["", "## Precedent", "The memory has nothing on this symbol yet."]

    return "\n".join(lines)


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    try:
        data = workup(symbol)
    except OracleXError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(summarize(symbol, data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
