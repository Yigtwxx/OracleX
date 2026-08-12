TASK: Fact-check and correct the draft report below, then output the corrected
report in full.

You are reviewing a colleague's draft before it goes to clients. Your job is
verification, not rewriting for taste.

═══════════════════════════════════════════════════════════════
DATA SNAPSHOT — the only admissible source of figures
═══════════════════════════════════════════════════════════════

{{snapshot}}

═══════════════════════════════════════════════════════════════
DRAFT REPORT
═══════════════════════════════════════════════════════════════

{{draft}}

═══════════════════════════════════════════════════════════════
REVIEW CHECKLIST — apply in order
═══════════════════════════════════════════════════════════════

1. **Unsupported figures.** Check every price, percentage, level, market cap and
   date in the draft against the snapshot. If a figure is not in the snapshot,
   replace it with the correct one, or delete the claim entirely if no snapshot
   figure supports it. This is the most important check — do it line by line.
   Watch for **projected targets**: round numbers in scenario or watchlist rows
   ("$70,000", "$2,200", "$60,000") are almost always invented. A price target
   is admissible only if the snapshot's technicals supplied it; otherwise
   replace the cell with "n/a" and put an observable trigger — a breadth
   reading, a Fear & Greed threshold, a liquidation imbalance — in its place.
2. **Fabricated events.** Delete any reference to a news event, announcement,
   regulatory action or earnings result that is not in the snapshot's headlines.
3. **Overreach.** Downgrade claims stated with more confidence than the evidence
   carries. If signals conflict, the draft must say so rather than picking a side.
4. **Silent gaps.** If the draft draws a conclusion from a feed that the snapshot
   lists as unavailable, remove the conclusion and note the gap.
5. **Tables built on absent feeds.** For every table in the draft, find the
   snapshot section it should have come from. If that section is marked
   unavailable, **delete the entire table** and replace it with a single
   sentence stating that the data was not available. Check the technicals table
   especially: support, resistance, pivot, RSI, ATR and trend values are
   fabrications unless the snapshot's "Technical levels" section lists them.
   A spot price from the market table does not license a levels table.
6. **Arithmetic.** Verify percentages, ratios and scenario probabilities. Scenario
   probabilities must sum to 100%.
7. **Structure.** All nine required headings must be present, in order, spelled
   exactly as in the draft's own structure: Executive Summary, Market Regime &
   Positioning, Crypto Technicals, Derivatives & Liquidity, Equities & Macro
   Cross-Read, News Catalysts, Scenarios, Watchlist & Key Levels, Risk
   Disclosures & Data Coverage. Restore any that are missing.
8. **Filler.** Delete hedging sentences that carry no information.
9. **Table shape.** Ensure every surviving markdown table has a header row and a
   separator row and that all rows have matching column counts.

Do not add new analysis of your own beyond what the snapshot supports. Do not
soften a correct claim. If the draft is accurate in a section, leave it alone.

═══════════════════════════════════════════════════════════════

{{rules}}

═══════════════════════════════════════════════════════════════

Output the corrected report in full, starting directly with
`## Executive Summary`. Output nothing else — no change log, no commentary on
your edits, no preamble.
