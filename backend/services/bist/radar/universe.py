"""
Which companies the Radar looks at.

The XU100 membership is a field on every scanner row rather than a list kept
anywhere, so the universe is a filter over the equity board — the same way the
ownership board and the heatmap pick theirs. A ticker with no price is dropped
here rather than carried as a row that every later stage has to skip.
"""

from services.bist.tradingview_client import EquityRow

UNIVERSE = "XU100"


def xu100_rows(equities: list[EquityRow]) -> list[EquityRow]:
    rows = [row for row in equities if UNIVERSE in row.indices and row.price]
    rows.sort(key=lambda row: -(row.market_cap or 0.0))
    return rows
