---
description: One Borsa İstanbul name — returns in all three frames, positioning, and who holds it
argument-hint: <ticker>  e.g. THYAO, ASELS, GARAN
allowed-tools: Bash
---

Work up `BIST:$1` against the running instance.

```bash
BASE="${ORACLE_X_URL:-http://localhost:8000}"
curl -sf "$BASE/api/bist/stocks/$1"
curl -sf "$BASE/api/bist/ownership/assets/$1"
```

**Before quoting a single number, read the return frames.** Every figure comes
back as `nominal`, `real` and `usd` together. Quoting the lira number alone
over a year in which consumer prices rose ~32% reports inflation as
performance — it is the most common way to be wrong about this market, and it
looks completely reasonable on the page.

* `nominal` — how many lira. As quoted.
* `real` — what those lira bought, deflated by TÜFE. The honest default for
  someone spending the money in Turkey.
* `usd` — the only frame comparable to a foreign asset.

A null `real` means the window could not be deflated. Say the real figure is
unavailable; do not pass the nominal one off in its place.

Quotes are delayed at least 15 minutes and `delay_minutes` says so. Never
present one as live.

If the ticker 404s, check the spelling rather than guessing — a bare ticker
does not resolve to Borsa İstanbul anywhere else in this terminal by design.
