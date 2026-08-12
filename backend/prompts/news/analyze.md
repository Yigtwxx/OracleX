TASK: Judge the price impact of the news item below on {{clean_symbol}}.

ANALYSIS DATE: {{report_date}}
ASSET: {{clean_symbol}} ({{asset_name}})
SYMBOL: {{symbol}}

═══════════════════════════════════════════════════════════════
MARKET DATA — the only admissible source of figures
═══════════════════════════════════════════════════════════════

{{price}}

{{technical}}

═══════════════════════════════════════════════════════════════
{{regime}}

═══════════════════════════════════════════════════════════════
{{rag_context}}

═══════════════════════════════════════════════════════════════
NEWS ITEM
═══════════════════════════════════════════════════════════════

HEADLINE:
"{{title}}"

FEED SUMMARY (truncated by the publisher's feed — not the full item):
{{summary}}

{{article}}

═══════════════════════════════════════════════════════════════
INSTRUCTIONS
═══════════════════════════════════════════════════════════════

Work through these in order:

0. **Read the source article first.** It, not the headline, is what you are
   judging. Quote it verbatim when you cite it — never paraphrase a figure it
   contains. Every claim in your reasoning must trace to a line you can quote
   from the article, a figure in the market data, or a figure in the regime
   block. If the article was not retrievable, say so, treat the headline and the
   truncated summary as all you have, and lower your confidence accordingly.
1. **Materiality.** Is this item material to the price, or is it commentary?
   Place it in one of the four impact categories. Most items are routine.
   Check whether the article is reporting something *new* or recapping an event
   that has already been priced — a recap is routine no matter how dramatic the
   headline.
2. **Mechanism.** If it is material, name the specific channel through which it
   would move the price — forced flow, a new buyer or seller, a change in
   expected cash flows, a change in access. A headline with no mechanism is not
   a catalyst.
3. **Direction.** Bullish, bearish, or neutral, following from the mechanism.
   Absent a mechanism, the answer is neutral.
4. **Confidence.** Apply the calibration table. Clarity of the news, not
   strength of your opinion, sets the number.
5. **Horizon.** How long before the impact, if any, is priced in.
6. **Regime.** Say how the current backdrop changes the reception. The same
   mechanism lands differently in a defensive tape than in a bid one: cite the
   specific regime figure that makes the difference — breadth, the Fear & Greed
   level and its direction, dominance, the liquidation balance — and say whether
   it amplifies or dampens the move. If the regime block is unavailable, say the
   backdrop could not be assessed rather than assuming one.
7. **Precedent.** If a precedent block was supplied above, say plainly which past
   event this item resembles and what happened after that one — "this resembles
   X; there the price did Y" — and let it adjust your confidence. Where a
   precedent notes that the durable outcome contradicted the headline, say so and
   do not let the tone of this headline alone settle your direction: a lawsuit,
   a ban or a collapse has repeatedly been followed by a higher price, and an
   approval or a record by a lower one. Weigh the mechanism against the
   precedent; do not simply copy the precedent's direction either.
   Those are past events — never present their figures as current, and never turn
   a precedent into a projection. If no precedent block was supplied, say that no
   comparable past event was found rather than inventing one.

Do not produce price levels, targets, support or resistance. Any levels that
exist are already in the market data block above; if that block says they are
unavailable, then none exist for this analysis and you must not construct them.

Respond with only the JSON object.
