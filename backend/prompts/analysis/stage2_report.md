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
24h change is not a trend reading. Support, resistance, RSI, ATR and trend exist
only if the technicals feed supplied them, and constructing them from prices is
fabrication.

Otherwise, work each covered asset in three passes.

**1 — The view from a distance.** Before any level, place the asset in its own
history: where in the multi-year range it trades, how far from that range's high
and low, where it sits against the 200-bar SMA, and what the swing structure is
doing. This is the paragraph that decides whether everything below is a dip in an
uptrend or a bounce in a downtrend, so it comes first.

**2 — The timeframes.** One row per timeframe, copied from the snapshot:

| Asset | TF | Trend | RSI(14) | RSI 5-bar | ATR % |

Then say in one or two sentences whether the timeframes agree. The snapshot
computes that agreement — quote it rather than deciding it yourself. Where they
conflict, name which horizon each signal belongs to: a bearish weekly with a
neutral 4h is a different statement from either alone. Read RSI as level *and*
direction — 40 and rising is not 40 and falling — and mention any divergence the
snapshot flagged, with the timeframe it was found on.

**3 — The zones.** Reproduce the snapshot's support and resistance bands:

| Asset | Side | Horizon | Zone | Distance | Confirmed on | Touches | Strength |

Copy each band **as a band**, both bounds, exactly as printed. Never quote a
single price as a level, never round a bound to a neater number, and never
introduce a level that is not in the table — the space between two bands is
empty because nothing traded there, not because a level is missing. Horizon is
the snapshot's, from the timeframe that confirmed the band; do not relabel a
long-horizon band as short-term because it happens to be close to spot.

Close with the read: which band is the one that matters over the {{timeframe}}
horizon, what a close beyond it would signal, and which band the structure says
price is more likely to reach first. Prefer bands with several touches, high
strength, and confirmation on more than one timeframe — say so when that is why
you picked one.

## Derivatives & Liquidity

Liquidation activity by side, the long/short balance, notable clusters, and
large-transaction flow. Explain what the positioning implies about where forced
flow would come from if price moves. If liquidation data is unavailable, say so
in one sentence and move on.

## Equities & Macro Cross-Read

Index performance, US market session status, and equity risk sentiment. Address
the cross-asset question directly: is crypto trading with risk assets or
decoupling? Cite the figures on both sides.

Then the macro leg, from the snapshot's "Commodities & macro" block: the dollar,
the metals and energy complex, and any ratio the board supplies. Say what the
combination implies about the liquidity backdrop crypto is trading in — a bid in
gold with a firm dollar is a different regime from both rising together. Quote
each price in the unit given; grains and softs are in US cents, and rewriting one
as dollars is a hundredfold error. If the commodity board is unavailable or
flagged as a replayed copy, say so here rather than reasoning from it.

## News Catalysts

The three catalysts from the evidence stage. For each: a bolded one-line summary,
then two to three sentences on the mechanism by which it would affect prices and
over what horizon. Skip anything that is recycled commentary — if fewer than
three items are genuinely material, present fewer and say why.

Where a headline carries a prior verdict in the snapshot, you may cite it — but
attribute it as one ("the news pipeline read this as bearish at 0.71 confidence")
and say where your own reading of the mechanism differs. A verdict is an opinion
on record, not a measured outcome, and it exists only because a reader opened
that item. Never present the tally of verdicts as the market's sentiment, and
never treat an unscored headline as neutral.

## Scenarios

| Scenario | Probability | Trigger | Key levels | Invalidation |

Base, Bull and Bear, probabilities summing to 100%. Every level referenced must
come from the snapshot's zone table, quoted as the band it is; if no technical
levels were available, use observable triggers instead (a breadth reading, a
Fear & Greed threshold, a liquidation imbalance) and leave the levels column as
"n/a". The invalidation column states
the specific observation that would end the scenario.

## Watchlist & Key Levels

| Asset | Zone | Horizon | Type | Why it matters |

Five to eight rows, ordered by importance over the {{timeframe}} horizon. Cover
all three horizons where the snapshot supplies them — a watchlist of five
short-term bands is a day-trading sheet, not a {{timeframe}} view. Every zone
must be copied from the snapshot's zone table as a band, with the horizon the
snapshot assigned it. If the technicals feed was unavailable, replace this table
with a short list of what to watch (assets, metrics and thresholds that the
snapshot does support) and say that price levels could not be computed.

## Risk Disclosures & Data Coverage

List the data feeds that were unavailable for this report and what could not be
assessed as a result. Then state the two largest risks to the thesis above. Close
with one line noting this is research commentary, not investment advice.

{{rules}}

═══════════════════════════════════════════════════════════════

Write the report now. Start directly with `## Executive Summary` — no title, no
preamble, no closing remarks beyond the final section.
