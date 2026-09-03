TASK: Decide what one Turkish market commentator said about one company, from
the transcript passages where the company is mentioned. Answer with JSON only.

COMPANY: {{company}} (ticker {{ticker}})
SPEAKER: {{speaker}}
VIDEO: {{title}} — published {{published}}

═══════════════════════════════════════════════════════════════
PASSAGES — Turkish, automatic captions, punctuation unreliable
═══════════════════════════════════════════════════════════════

{{passages}}

═══════════════════════════════════════════════════════════════
INSTRUCTIONS
═══════════════════════════════════════════════════════════════

Return exactly this JSON object and nothing else:

{"stance": "bullish" | "bearish" | "neutral" | "none",
 "horizon_days": <integer or null>,
 "target": <number or null>,
 "quote": "<one verbatim sentence from the passages, in Turkish>"}

1. `stance` is about **this company's share price**, in the speaker's own view.
   `bullish` — expects it to rise, would buy, sees a setup, names an upside
   target. `bearish` — expects it to fall, would sell or avoid, sees a
   breakdown. `neutral` — discusses the company without a directional view, or
   explicitly says wait. `none` — the mention is incidental (a list of index
   members, a comparison, a past event) and carries no view at all.
2. `horizon_days` is how far ahead the view reaches, in calendar days, **only if
   the speaker says so** ("bu hafta" → 7, "ay sonuna kadar" → 30, "orta vade"
   → 90). Otherwise null. Never guess one.
3. `target` is a price level the speaker names for this company, as a plain
   number in lira. Only a level clearly attached to this company. Otherwise null.
4. `quote` must be copied from the passages word for word — the sentence that
   best carries the stance. If `stance` is `none`, quote the mention itself.
5. Reported speech is not the speaker's view: "analistler yükselir diyor" with
   no agreement from the speaker is `neutral`. Sarcasm and questions are not
   views either.
6. If the passages are about a different company with a similar name, answer
   `none`.

No prose, no markdown fence, no explanation. JSON only.
