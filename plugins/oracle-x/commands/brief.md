---
description: The day's briefing — macro regime, market overview and what the vector memory says resembles now
allowed-tools: mcp__oracle-x__check_instance, mcp__oracle-x__get_daily_brief, mcp__oracle-x__get_macro_regime, mcp__oracle-x__get_market_overview, mcp__oracle-x__list_news
---

Assemble the morning read from the running instance.

1. `check_instance`. If nothing answers, stop and say so.
2. `get_daily_brief` — the vector memory's own summary of what resembles today.
3. `get_macro_regime` — the computed label and score. The label is always
   present; the written note may not be. Say which you are quoting.
4. `get_market_overview` for the state, `list_news` for what moved it.

Lead with the regime label and the one thing that changed since yesterday, then
the memory's read. Keep it to something a person reads before the open.

If a category is degraded, answer with what the healthy ones returned and name
the gap. A partial brief that says what is missing beats a complete-looking one
that quietly dropped a source.
