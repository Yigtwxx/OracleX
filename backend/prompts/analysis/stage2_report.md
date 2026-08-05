TASK: Write the {{timeframe}} market intelligence report.

REPORT HORIZON: {{timeframe}}
REPORT DATE: {{report_date}}

═══════════════════════════════════════════════════════════════
DATA SNAPSHOT — the only source of truth for figures
═══════════════════════════════════════════════════════════════

{{snapshot}}

═══════════════════════════════════════════════════════════════
EXTRACTED EVIDENCE — from the preceding analysis stage
═══════════════════════════════════════════════════════════════

{{evidence}}

═══════════════════════════════════════════════════════════════
REQUIRED STRUCTURE — use these exact headings, in this order
═══════════════════════════════════════════════════════════════

## Executive Summary

Three to five sentences. Open with the single-sentence thesis for the
{{timeframe}} horizon, then the two facts that most support it, then the main
thing that would disprove it. End with a conviction level — **High**, **Moderate**,
or **Low** — and one clause explaining why that level and not another.

## Market Regime & Positioning

Characterise the current regime using Fear & Greed (level and its multi-day
direction), market breadth, BTC/ETH dominance and realised volatility. State
whether positioning looks crowded, neutral, or washed out, and on what evidence.
Where the evidence stage flagged a contradiction, surface it here rather than
smoothing it over.

## Crypto Technicals

**If the snapshot's "Technical levels" section is marked unavailable, write one
sentence saying levels could not be computed for this report and nothing else in
this section. Do NOT produce the table.** A spot price is not a support level; a
24h change is not a trend reading. Support, resistance, pivot, RSI, ATR and trend
exist only if the technicals feed supplied them, and constructing them from
prices is fabrication.

Otherwise, reproduce a table for the majors covered in the snapshot, copying the
values exactly as given:

| Asset | Price | Trend | RSI | Support | Resistance | Pivot | ATR |

Follow the table with a short read on what the levels imply: which level is the
one that matters, and what a break of it would signal. Only use levels present
in the snapshot.

## Derivatives & Liquidity

Liquidation activity by side, the long/short balance, notable clusters, and
large-transaction flow. Explain what the positioning implies about where forced
flow would come from if price moves. If liquidation data is unavailable, say so
in one sentence and move on.

## Equities & Macro Cross-Read

Index performance, US market session status, and equity risk sentiment. Address
the cross-asset question directly: is crypto trading with risk assets or
decoupling? Cite the figures on both sides.

## News Catalysts

The three catalysts from the evidence stage. For each: a bolded one-line summary,
then two to three sentences on the mechanism by which it would affect prices and
over what horizon. Skip anything that is recycled commentary — if fewer than
three items are genuinely material, present fewer and say why.

## Scenarios

| Scenario | Probability | Trigger | Key levels | Invalidation |

Base, Bull and Bear, probabilities summing to 100%. Every level referenced must
come from the snapshot; if no technical levels were available, use observable
triggers instead (a breadth reading, a Fear & Greed threshold, a liquidation
imbalance) and leave the levels column as "n/a". The invalidation column states
the specific observation that would end the scenario.

## Watchlist & Key Levels

| Asset | Level | Type | Why it matters |

Five to eight rows, ordered by importance over the {{timeframe}} horizon. Every
value in the Level column must be copied from the snapshot. If the technicals
feed was unavailable, replace this table with a short list of what to watch
(assets, metrics and thresholds that the snapshot does support) and say that
price levels could not be computed.

## Risk Disclosures & Data Coverage

List the data feeds that were unavailable for this report and what could not be
assessed as a result. Then state the two largest risks to the thesis above. Close
with one line noting this is research commentary, not investment advice.

═══════════════════════════════════════════════════════════════

Write the report now. Start directly with `## Executive Summary` — no title, no
preamble, no closing remarks beyond the final section.
