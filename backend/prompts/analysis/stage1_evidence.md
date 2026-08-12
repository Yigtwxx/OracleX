TASK: Extract evidence from the market data snapshot below. Do NOT write a
report — this is the evidence-gathering stage that a later stage will write from.

REPORT HORIZON: {{timeframe}}
REPORT DATE: {{report_date}}

═══════════════════════════════════════════════════════════════
DATA SNAPSHOT
═══════════════════════════════════════════════════════════════

{{snapshot}}

═══════════════════════════════════════════════════════════════
INSTRUCTIONS
═══════════════════════════════════════════════════════════════

Work through the snapshot systematically and produce structured evidence:

1. **key_observations** — the 6-10 most decision-relevant facts. Each must cite
   the exact figure from the snapshot. Rank by importance to a {{timeframe}}
   horizon. An observation that repeats a number without an interpretation is
   not an observation.
2. **confirmations** — where two or more independent signals agree (e.g. breadth
   and Fear & Greed both defensive; RSI and trend both extended). Name both
   signals and their values.
3. **contradictions** — where signals disagree. These are the most valuable part
   of the analysis. If price is up but breadth is negative, that is a
   contradiction worth surfacing.
4. **data_gaps** — feeds listed as unavailable, plus any conclusion that cannot
   be drawn because of them. Be specific about what could NOT be assessed.
5. **themes** — 2-4 narrative threads that tie the observations together, each
   with the evidence that supports it.
6. **catalysts** — from the news headlines, the 3 items most likely to be
   materially priced in over the {{timeframe}} horizon, each with a one-line
   reason. If the headlines are all routine commentary, say so and return fewer.

Rules:
- Only use figures present in the snapshot above. Never introduce a number that
  is not there.
- If a section has nothing to report, return an empty array — do not pad it.
- Be skeptical. Routine price commentary is not a catalyst.

{{rules}}

═══════════════════════════════════════════════════════════════

Respond with ONLY this JSON object and nothing else:

{
  "key_observations": [{"observation": "...", "evidence": "...", "importance": "high|medium|low"}],
  "confirmations": [{"claim": "...", "signals": ["...", "..."]}],
  "contradictions": [{"tension": "...", "signals": ["...", "..."]}],
  "data_gaps": [{"missing": "...", "impact": "..."}],
  "themes": [{"theme": "...", "support": "..."}],
  "catalysts": [{"headline": "...", "why_it_matters": "..."}]
}
