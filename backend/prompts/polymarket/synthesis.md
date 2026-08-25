# Task — weigh the case and say which side the evidence favours

## The market

Question: {{question}}
Resolves: {{resolution_criteria}}
Closes: {{end_date}}

## Facts

{{facts}}

## What the order book says

{{microstructure}}

## The case on both sides

{{arguments}}

## Evidence

{{evidence}}

## What the sweep reached

{{coverage}}

## Reading this category

{{category_guidance}}

## What to return

A JSON object:

```json
{
  "leaning": "yes",
  "confidence": 0.62,
  "bottom_line": "At most three sentences. Every one carries an inline [S3] marker naming a source you were given.",
  "claims_for": [
    { "text": "One sentence.", "sources": ["S1"], "direction": "yes", "weight": "strong" }
  ],
  "claims_against": [
    { "text": "One sentence.", "sources": ["S2"], "direction": "no", "weight": "moderate" }
  ]
}
```

- `leaning` is `yes`, `no`, or `unclear`. `unclear` is a real answer and is the
  right one when the strong claims on each side do not resolve against each
  other.
- `confidence` is how much the *evidence* supports your leaning, from 0 to 1. It
  is not the probability of the event, and it is not the market price. Two
  corroborated wire reports pointing one way is around 0.7; one outlet and an
  inference is around 0.3.
- **Do not anchor on the market price.** You have been told what it is so you can
  note where your reading differs from it. A verdict that simply restates the
  quoted odds has added nothing.
- Every sentence in `bottom_line` must carry a marker like `[S3]`. Sentences
  without one are deleted before the reader sees them, which will leave your
  summary shorter than you wrote it.

{{rules}}
