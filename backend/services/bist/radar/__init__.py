"""
The Radar: which XU100 names sit in a pullback inside an uptrend right now.

A funnel, cheapest stage first. The equity board's snapshot columns gate the
whole index without a request; daily candles are fetched only for the names
that pass; the financial statements are read for the whole universe but from a
quarter-aware disk cache, so after the first scan they cost nothing; and the
model is asked to write only for the handful of finalists, never to score.

Zero candidates is a result. The scan says "no setup today" and names the
closest misses rather than lowering the bar until something passes.
"""
