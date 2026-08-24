"""
Reading the previous close out of Yahoo's v8 chart payload.

Shared by every service that takes a daily change from that endpoint, because
the field that looks like the answer is not one and the mistake is invisible in
the number it produces.

`meta.chartPreviousClose` is the close preceding the *requested range window*,
not the previous session. It therefore moves with the `range` parameter: ask for
`range=2d` and it answers with a close two sessions back, `range=5d` and it is
five sessions back. Both come out as a plausible-looking percentage. Measured on
2026-08-21, the global ticker showed the DAX at -0.16% on a session it closed
+0.26%, and the stock detail card read AAPL +1.98% on a day it fell -1.75% — the
sign itself was wrong, which is the failure this terminal tolerates least.

The daily bars in the same payload are unambiguous, so the reference close is
read from them instead. `meta.previousClose` is kept as a last resort because it
is a genuine prior-session field that does not depend on the range; only
`chartPreviousClose` is refused outright.
"""

from typing import Any, Mapping

# A daily bar is stamped at its session's open, so a `regularMarketTime` inside
# the same session lands hours after it. A full day of distance means the quote
# belongs to a session Yahoo has not opened a bar for yet — pre-market on a
# venue whose bar appears late — and the last bar is then already the previous
# close rather than the current one.
SAME_SESSION_WINDOW = 24 * 3600


def previous_close(payload: Any) -> float | None:
    """
    The close of the session before the one `regularMarketPrice` belongs to.

    `None` when the payload carries fewer bars than that needs and no
    `previousClose` either: a reference that could not be read is reported as a
    missing change, never as a flat 0%.
    """
    try:
        result = payload["chart"]["result"][0]
        meta = result["meta"]
    except (KeyError, IndexError, TypeError):
        return None

    from_bars = _previous_close_from_bars(result, meta)
    if from_bars is not None:
        return from_bars

    fallback = meta.get("previousClose")
    return float(fallback) if fallback else None


def _previous_close_from_bars(result: Mapping[str, Any], meta: Mapping[str, Any]) -> float | None:
    """The prior session's close as the daily bars record it, or `None`."""
    try:
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None

    bars = [
        (int(ts), float(close))
        for ts, close in zip(timestamps, closes)
        if ts is not None and close is not None
    ]
    if not bars:
        return None

    market_time = meta.get("regularMarketTime")
    session_gap = None if market_time is None else int(market_time) - bars[-1][0]
    quote_has_its_own_bar = session_gap is None or session_gap < SAME_SESSION_WINDOW

    if quote_has_its_own_bar:
        return bars[-2][1] if len(bars) > 1 else None
    return bars[-1][1]
