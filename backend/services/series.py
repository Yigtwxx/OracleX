"""Shared helpers for price series that are drawn rather than read."""

# Sparklines are drawn ~100px wide, so a denser series buys nothing on screen
# while costing bandwidth on every row of a 250-row table. Both the crypto and
# the equity overview thin their series to this many points.
SPARKLINE_POINTS = 24


def downsample(points: list[float], target: int = SPARKLINE_POINTS) -> list[float]:
    """Evenly thin a series to at most `target` points, always keeping the last."""
    if not points:
        return []
    if len(points) <= target:
        return [float(p) for p in points]

    step = len(points) / target
    thinned = [float(points[int(i * step)]) for i in range(target)]
    # The final point is the current price; an evenly-strided pick can miss it.
    thinned[-1] = float(points[-1])
    return thinned
