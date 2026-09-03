---
description: VİOP positioning for one underlying, drawn against Takasbank's published scan range
argument-hint: <ticker>  e.g. THYAO, GARAN
allowed-tools: Bash
---

Read where VİOP positions sit for `$1`.

```bash
BASE="${ORACLE_X_URL:-http://localhost:8000}"
curl -sf "$BASE/api/bist/viop-map/underlyings"      # is this ticker covered at all?
curl -sf "$BASE/api/bist/viop-map/$1"
curl -sf "$BASE/api/bist/viop-map/$1/note"
```

Ask the coverage endpoint first. The map is built only where the data supports
it, and coverage is narrower than the exchange's contract list — an uncovered
ticker is a real answer, not a failure.

**The band is not a margin call, and saying otherwise is the one mistake this
command exists to prevent.** It is Takasbank's price scan range: the one-day,
99% confidence move the clearing house sized a position's *initial* margin
against. VİOP publishes no maintenance margin rate — the CCP procedure leaves
the level to a General Letter and states maintenance is not applied at end of
day. The "75% of initial" figure circulating online traces to a single undated
guide. So the price at which a call actually fires cannot be computed from
anything public, and must not be implied.

Whatever you write, the caption has to survive being read alone: "the move the
initial margin was sized for" is true, "where you get liquidated" is not.

One further caveat worth passing on: direction is inferred, not published. Open
interest rising into a rising settlement is read as longs opening, rising
against a falling one as shorts. Everything else on that surface — exposure,
entry price, the swept range, the band — comes from the exchange or the
clearing house.
