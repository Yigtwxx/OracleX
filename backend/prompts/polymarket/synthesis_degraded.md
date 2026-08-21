# Task — say what the thin evidence supports, and no more

The sweep for this market came back below the standard a plain verdict requires.
You are being asked anyway, on the condition that the answer states its own
limits. Confidence is capped after you reply, so a high number here buys nothing.

## The market

Question: {{question}}
Resolves: {{resolution_criteria}}
Closes: {{end_date}}

## Facts

{{facts}}

## What the order book says

{{microstructure}}

## Why this market exists

{{origin}}

## The case on both sides

{{arguments}}

## Evidence

{{evidence}}

## What the sweep reached

{{coverage}}

## What is missing

{{gaps}}

## Reading this category

{{category_guidance}}

## What to return

A JSON object:

```json
{
  "leaning": "unclear",
  "confidence": 0.3,
  "bottom_line": "At most three sentences, each carrying an inline [S3] marker.",
  "claims_for": [
    { "text": "One sentence.", "sources": ["S1"], "direction": "yes", "weight": "weak" }
  ],
  "claims_against": [],
  "gaps": [
    "One sentence naming something the evidence could not settle."
  ]
}
```

- **`unclear` is the expected answer here.** Reach for `yes` or `no` only when a
  single fact settles the question outright — a scheduled event already having
  happened, a deadline already passed. Thin evidence pointing one way is thin
  evidence.
- **`gaps` is the point of this stage.** Name what you would have needed. "No
  reporting after the 14th", "only one outlet covered the vote", "the resolution
  criteria turn on a definition no source addresses" — these tell the reader what
  the answer is worth.
- Do not compensate for missing evidence with reasoning. A long chain of
  inference from two headlines is less honest than a short answer that says two
  headlines is what there was.

{{rules}}
