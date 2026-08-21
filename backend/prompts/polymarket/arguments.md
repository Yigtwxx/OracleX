# Task — build the case on both sides

Set out what the evidence says for and against this outcome. Not a verdict yet:
the strongest version of each side, so the next stage weighs arguments rather
than impressions.

## The market

Question: {{question}}
Resolves: {{resolution_criteria}}
Closes: {{end_date}}

## Facts

{{facts}}

## Why this market exists

{{origin}}

## Evidence

{{evidence}}

## Reading this category

{{category_guidance}}

## What to return

A JSON object:

```json
{
  "claims_for": [
    {
      "text": "One sentence.",
      "sources": ["S1", "S4"],
      "direction": "yes",
      "weight": "strong"
    }
  ],
  "claims_against": [
    { "text": "One sentence.", "sources": ["S2"], "direction": "no", "weight": "moderate" }
  ]
}
```

- `weight` is `strong` when more than one independent outlet reports the same
  thing, `moderate` when one credible outlet does, `weak` when it is an inference
  you drew or rests on a single partisan source.
- Aim for three to six claims a side. Fewer is honest when the evidence is thin;
  padding it with restatements is not.
- A claim that appears on both sides is a claim you have not finished thinking
  about. Put it on the side it actually supports.

{{rules}}
