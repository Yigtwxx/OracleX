# Task — why does this market exist, and what moved it

A prediction market is written by somebody, at a moment, because something made
the question worth asking. Your job is to name that something, and to name what
moved the price afterwards. When the reporting does not let you name it, say
what *kind* of thing opens a market like this one — clearly, as a possibility.

## The market

Question: {{question}}
Opened: {{created_at}}
Closes: {{end_date}}
Category: {{category}}
Resolves: {{resolution_criteria}}

## The windows

Each window below is either the market's opening or a measured sharp move in its
price. The timestamps are not estimates — they are when the price actually
changed.

{{windows}}

## Candidate stories

{{candidates}}

## Reading this category

{{category_guidance}}

## What to return

A JSON object:

```json
{
  "opening_rationale": "One or two sentences on what made this question worth asking, cited to a candidate id, or null if the dated reporting does not say.",
  "triggers": [
    {
      "summary": "What happened, in one sentence.",
      "source_id": "S3",
      "move_index": 0
    }
  ],
  "conjecture": "One or two sentences naming a plausible reason, phrased as a possibility. Fill this every time.",
  "conjecture_basis": [
    "One short line per thing this rests on."
  ]
}
```

Rules specific to this stage:

- **A trigger must cite an `S` id.** The candidate list has two namespaces: `S`
  is dated and inside a window, `C` is background — undated, or published outside
  every window. A trigger citing a `C` id is deleted, and so is one citing an id
  that is on neither list. If no `S` candidate plausibly explains a window, emit
  no trigger for that window. An unexplained move is a fact; an invented
  explanation is not.
- **Coincidence in time is not causation, but it is the only evidence you have
  here.** Say what the story was and let the timing speak. Do not assert that it
  *caused* the move unless the story itself makes the connection.
- **`opening_rationale` may be null.** Many markets are opened because a venue
  lists a category, not because anything happened. Saying so is better than
  manufacturing a reason.

{{rules}}

═══════════════════════════════════════════════════════════════
ONE EXCEPTION, FOR THIS STAGE ONLY — it applies to `conjecture` and
`conjecture_basis` and to nothing else on this page
═══════════════════════════════════════════════════════════════

Rule 2 above requires a source id for every claim. `conjecture` is the single
field in this system that carries none, because it is not a claim about what
happened — it is a claim about what usually causes a question like this one to be
written. It is shown to the reader under an "unverified" badge, separately from
anything sourced, and it is never passed to the stage that writes the verdict.

Write it under these conditions:

1. **Write it on every reply, whatever else you filled.** It is thrown away
   automatically when a sourced answer survives, so it costs nothing — and you
   cannot tell in advance which of your triggers will survive, because one citing
   a `C` id is deleted after you have replied. Leaving `conjecture` null because
   you named a trigger is how a market ends up showing the reader nothing at all.
2. **Name the mechanism, not an event.** You may name the institutions, actors
   and kinds of event that decide questions in this category, and say that one of
   them is the likely occasion — "a market like this usually opens around an SEC
   enforcement action or a public statement from the Chair". You may **not**
   assert that a particular event occurred, on a particular date, to a particular
   person. "The SEC said X on 14 March" is a fabrication whether or not it is
   true; you were given no source for it and you are not the source.
3. **Use the dates you were given.** The opening date, the closing date and the
   resolution criteria are facts on this page and may be reasoned from. Any other
   date is one you invented.
4. **Phrase it as a possibility and mean it.** "It may have been opened
   because…", "questions like this usually follow…". A conjecture written in the
   indicative is a lie with a hedge missing.
5. **`conjecture_basis` shows your working.** One line each for what the
   hypothesis rests on — the category's mechanism, the opening date's proximity to
   something in the resolution criteria, the absence of any reporting. A reader
   who disagrees with the basis can discard the conjecture, which is the only
   thing that makes printing it defensible.
6. **If you have nothing, return null.** A conjecture that would fit any market
   in this category on any day — "interest in this topic increased" — says
   nothing and is worse than the silence it replaces.
