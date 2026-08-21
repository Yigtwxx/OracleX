# Task — why does this market exist, and what moved it

A prediction market is written by somebody, at a moment, because something made
the question worth asking. Your job is to name that something, and to name what
moved the price afterwards.

## The market

Question: {{question}}
Opened: {{created_at}}
Category: {{category}}

## The windows

Each window below is either the market's opening or a measured sharp move in its
price. The timestamps are not estimates — they are when the price actually
changed.

{{windows}}

## Candidate stories

These were published inside those windows. The id and the window index are what
tie a story to a move.

{{candidates}}

## What to return

A JSON object:

```json
{
  "opening_rationale": "One or two sentences on what made this question worth asking, or null if the evidence does not say.",
  "triggers": [
    {
      "summary": "What happened, in one sentence.",
      "source_id": "S3",
      "move_index": 0
    }
  ]
}
```

Rules specific to this stage:

- **A trigger must be a story from the candidate list, cited by its id.** If no
  candidate plausibly explains a window, emit no trigger for that window. An
  unexplained move is a fact; an invented explanation is not.
- **Coincidence in time is not causation, but it is the only evidence you have
  here.** Say what the story was and let the timing speak. Do not assert that it
  *caused* the move unless the story itself makes the connection.
- **`opening_rationale` may be null.** Many markets are opened because a venue
  lists a category, not because anything happened. Saying so is better than
  manufacturing a reason.

{{rules}}
