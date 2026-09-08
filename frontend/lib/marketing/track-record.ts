/**
 * The accuracy page, as content.
 *
 * The same rule as `sections.ts`, and it matters more here than anywhere else
 * on the site: **the prose carries no digits.** Every number belongs to the
 * board, which reads the live record. A hit rate written into a sentence is a
 * claim that ages silently, and it would age on the one page whose entire
 * argument is that this terminal does not let its claims age.
 *
 * `track-record.test.ts` enforces it.
 */

import type { DocSection } from './sections';

export const TRACK_RECORD_SECTIONS: readonly DocSection[] = [
  {
    id: 'record',
    index: '01',
    label: 'Record',
    title: 'The calls, and what happened next',
    body: [
      'Every news item the terminal analyses ends in a direction: bullish, bearish or neutral, for a named asset, at a moment that is written down. That is a falsifiable claim, and it was going unchecked — the verdicts were kept on disk with an empty slot beside each one, waiting for a measurement that nothing ever wrote.',
      'This is that measurement. A scheduled job takes each verdict, reads what the price actually did over the horizons that have since come due, and appends the result. Nothing is rewritten: a row is written once, when its horizon first becomes measurable, and the longest of them lands a year after the call it scores.',
    ],
  },
  {
    id: 'baseline',
    index: '02',
    label: 'Baseline',
    title: 'A hit rate alone proves nothing',
    body: [
      'Beside every rate is what the best fixed answer would have scored on exactly the same calls — always-bullish, always-bearish or always-neutral, whichever won. A model that says bullish into a market that mostly rose has demonstrated nothing by being right, and a page that printed the hit rate on its own would be inviting the opposite conclusion.',
      'The benchmark shares its denominator with the rate it qualifies, which is the only way the gap between them means anything. Where the sample is too thin to state either, both are withheld and the count stands alone.',
    ],
  },
  {
    id: 'measured',
    index: '03',
    label: 'Method',
    title: 'Measured from the call, not the headline',
    body: [
      'The horizons run from the moment the verdict existed rather than from the article that prompted it. Measuring from publication would credit the model with whatever the price did while the analysis was still running — a move no reader could have acted on, because the call had not been made yet. The baseline is the last close before the day of the verdict, and the lag between headline and verdict is kept on every row.',
      'Neutral verdicts are scored, and never pooled with the directional ones. Staying inside the flat band is the easiest of the three claims and the one the model reaches for most often, so folding it into the headline would lift the figure with the verdict that risks least.',
    ],
  },
  {
    id: 'gaps',
    index: '04',
    label: 'Gaps',
    title: 'What is missing is counted too',
    body: [
      'A horizon the venues cannot price is recorded as unmeasurable rather than dropped, and a verdict whose direction came from a word count — the fallback when no model was reachable — is excluded from the rate and reported separately. Both are on the board, because a denominator that quietly loses its inconvenient rows is the easiest way to manufacture a record.',
      'The whole thing exports as a table, one row per call and horizon, unresolved calls included. The reasoning is the same: a file that contained only what resolved would describe a different and much kinder record than the one being claimed.',
    ],
  },
];
