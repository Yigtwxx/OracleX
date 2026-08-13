import { BTC_SERIES, CANDLE_COUNT, REGIME_BOUNDS } from './candle-series';
import { progressOfCandle, StageKey, within } from './stages';

/**
 * One piece of the fake technical analysis drawn over the tape.
 *
 * Every price-bearing mark refers to a candle *index* rather than a hard-coded
 * price, so the annotations stay pinned to the story when the series changes.
 */
export type Mark =
  | { readonly kind: 'ma'; readonly period: number; readonly tone: 'accent' | 'muted' }
  | {
      readonly kind: 'level';
      readonly index: number;
      readonly anchor: 'high' | 'low';
      readonly label: string;
      readonly tone: 'up' | 'down';
    }
  | {
      readonly kind: 'trendline';
      readonly from: number;
      readonly to: number;
      readonly anchor: 'high' | 'low';
      readonly label: string;
    }
  | {
      readonly kind: 'zone';
      readonly from: number;
      readonly to: number;
      readonly label: string;
      readonly tone: 'up' | 'down';
    }
  | {
      readonly kind: 'callout';
      readonly index: number;
      readonly anchor: 'high' | 'low';
      readonly title: string;
      readonly detail: string;
    }
  | { readonly kind: 'measure'; readonly from: number; readonly to: number }
  | { readonly kind: 'sweep'; readonly index: number; readonly label: string }
  | {
      /**
       * Head and shoulders. `anchor: 'low'` draws the inverse — the same three
       * pivots read off the other side of the bars, which is the only thing
       * that actually differs between the two patterns.
       *
       * Only the three pivots are stated. The neckline runs through whatever
       * sits between them, and finding that is geometry the renderer can do
       * from the series it already holds.
       */
      readonly kind: 'headShoulders';
      readonly left: number;
      readonly head: number;
      readonly right: number;
      readonly anchor: 'high' | 'low';
      readonly label: string;
      readonly tone: 'up' | 'down';
    }
  | {
      /** Two converging trendlines over a range, drawn from its own pivots. */
      readonly kind: 'wedge';
      readonly from: number;
      readonly to: number;
      readonly label: string;
      readonly tone: 'up' | 'down';
    };

export interface ScheduledMark {
  readonly from: number;
  readonly to: number;
  readonly mark: Mark;
}

/** Highest candle index a mark reads. `-1` for marks that follow the whole tape. */
export function maxIndexOf(mark: Mark): number {
  switch (mark.kind) {
    case 'ma':
      return -1;
    case 'level':
    case 'callout':
    case 'sweep':
      return mark.index;
    case 'trendline':
    case 'zone':
    case 'measure':
    case 'wedge':
      return Math.max(mark.from, mark.to);
    case 'headShoulders':
      return mark.right;
  }
}

const [ACCUMULATION, IMPULSE, PULLBACK, MARKUP, BLOWOFF, DISTRIBUTION, CAPITULATION, RECOVERY] =
  REGIME_BOUNDS;

function argExtreme(from: number, to: number, pick: 'high' | 'low'): number {
  const { candles } = BTC_SERIES;
  let best = from;
  for (let i = from; i <= to; i += 1) {
    if (pick === 'high' ? candles[i].h > candles[best].h : candles[i].l < candles[best].l) best = i;
  }
  return best;
}

const IMPULSE_HIGH = argExtreme(IMPULSE.start, IMPULSE.end, 'high');
const ACCUMULATION_LOW = argExtreme(ACCUMULATION.start, ACCUMULATION.end, 'low');
const BLOWOFF_HIGH = argExtreme(BLOWOFF.start, BLOWOFF.end, 'high');
const CAPITULATION_LOW = argExtreme(CAPITULATION.start, CAPITULATION.end, 'low');
const RECOVERY_LOW = argExtreme(RECOVERY.start, RECOVERY.start + 12, 'low');

/**
 * Pivots for the two head-and-shoulders patterns, found in the data rather than
 * written down.
 *
 * The series is generated from a seed, so any index typed in here would be a
 * number that happens to be right today. Reading the extreme out of the range
 * the story puts it in means the pattern still lands on real pivots if the seed
 * or the regime lengths ever move.
 *
 * The head of the top is the blow-off high and the head of the inverse is the
 * capitulation low, which is also what the callout and the sweep point at — the
 * marks agree with each other because they are all reading the same bars.
 */
const HS_HEAD = BLOWOFF_HIGH;
const HS_LEFT = argExtreme(MARKUP.start + 4, MARKUP.end - 3, 'high');
const HS_RIGHT = argExtreme(DISTRIBUTION.start + 2, DISTRIBUTION.end, 'high');

const IHS_HEAD = CAPITULATION_LOW;
const IHS_LEFT = argExtreme(DISTRIBUTION.start + 4, CAPITULATION.start - 1, 'low');
const IHS_RIGHT = argExtreme(IHS_HEAD + 5, RECOVERY.start + 16, 'low');

/**
 * Places a mark inside a stage's scroll window, then pushes it later if the
 * candles it draws on have not printed yet — keeping the duration intact.
 *
 * This is what makes "no Fibonacci over blank space" a property of the code
 * rather than of careful hand-tuning. `analysis-marks.test.ts` asserts it holds
 * for every mark, so a future edit to STAGES cannot silently break it.
 */
function schedule(key: StageKey, startFrac: number, endFrac: number, mark: Mark): ScheduledMark {
  const slot = within(key, startFrac, endFrac);
  const maxIndex = maxIndexOf(mark);
  const earliest = maxIndex < 0 ? 0 : progressOfCandle(maxIndex, CANDLE_COUNT);
  const from = Math.max(slot.from, earliest);
  return { from, to: from + (slot.to - slot.from), mark };
}

export const ANALYSIS_MARKS: readonly ScheduledMark[] = [
  // One or two marks per stage, ordered so the story on the tape runs alongside
  // the story in the copy: moving averages while the pipeline is explained, the
  // levels while the live board is, the reversal while positioning is.

  // ── Analysis ──────────────────────────────────────────────────────────────
  schedule('ai', 0.05, 0.45, { kind: 'ma', period: 20, tone: 'accent' }),
  schedule('ai', 0.28, 0.72, { kind: 'ma', period: 50, tone: 'muted' }),

  // ── Oracle chat ───────────────────────────────────────────────────────────
  // The wedge sits inside the markup rather than in the accumulation range it
  // would be most textbook in: the early bars are seeded and have already
  // panned off the left edge by the time this stage arrives, and a pattern
  // drawn on candles nobody can see is worse than no pattern.
  schedule('chat', 0.04, 0.5, {
    kind: 'wedge',
    from: MARKUP.start + 3,
    to: MARKUP.end - 2,
    label: 'Rising wedge',
    tone: 'down',
  }),
  schedule('chat', 0.3, 0.72, {
    kind: 'callout',
    index: IMPULSE.start + 1,
    anchor: 'low',
    title: 'Breakout confirmed',
    detail: 'Volume 2.4× the 20-bar mean',
  }),

  // ── Market data ───────────────────────────────────────────────────────────
  schedule('live', 0.05, 0.4, {
    kind: 'level',
    index: IMPULSE_HIGH,
    anchor: 'high',
    label: 'Resistance',
    tone: 'down',
  }),
  schedule('live', 0.34, 0.7, {
    kind: 'level',
    index: ACCUMULATION_LOW,
    anchor: 'low',
    label: 'Support',
    tone: 'up',
  }),

  // ── Screening ─────────────────────────────────────────────────────────────
  schedule('heatmap', 0.08, 0.46, {
    kind: 'zone',
    from: PULLBACK.start,
    to: PULLBACK.end,
    label: 'Demand',
    tone: 'up',
  }),
  schedule('heatmap', 0.5, 0.86, {
    kind: 'callout',
    index: PULLBACK.end - 4,
    anchor: 'low',
    title: 'Retest holds',
    detail: 'Prior resistance flips to support',
  }),

  // ── Macro context ─────────────────────────────────────────────────────────
  schedule('macro', 0.1, 0.5, {
    kind: 'callout',
    index: BLOWOFF_HIGH,
    anchor: 'high',
    title: 'Blow-off top',
    detail: 'Upper wicks expand, bid thins out',
  }),
  schedule('macro', 0.22, 0.64, {
    kind: 'headShoulders',
    left: HS_LEFT,
    head: HS_HEAD,
    right: HS_RIGHT,
    anchor: 'high',
    label: 'Head and shoulders',
    tone: 'down',
  }),
  schedule('macro', 0.48, 0.86, { kind: 'measure', from: IMPULSE.start, to: BLOWOFF_HIGH }),

  // ── Positioning ───────────────────────────────────────────────────────────
  schedule('ownership', 0.06, 0.44, {
    kind: 'zone',
    from: DISTRIBUTION.start,
    to: DISTRIBUTION.end,
    label: 'Supply',
    tone: 'down',
  }),
  schedule('ownership', 0.56, 0.9, {
    kind: 'sweep',
    index: CAPITULATION_LOW,
    label: 'Liquidity swept',
  }),
  // Deliberately over the same low as the sweep above. The sweep says a wick
  // took out the stops; the inverse pattern says that wick turned out to be the
  // head. Two readings of one bar is the argument this page is about.
  schedule('ownership', 0.5, 0.94, {
    kind: 'headShoulders',
    left: IHS_LEFT,
    head: IHS_HEAD,
    right: IHS_RIGHT,
    anchor: 'low',
    label: 'Inverse head and shoulders',
    tone: 'up',
  }),

  // ── Community ─────────────────────────────────────────────────────────────
  schedule('social', 0.1, 0.56, {
    kind: 'trendline',
    from: CAPITULATION_LOW,
    to: RECOVERY_LOW,
    anchor: 'low',
    label: 'Higher lows',
  }),
  schedule('social', 0.62, 0.95, {
    kind: 'callout',
    index: RECOVERY.start + 16,
    anchor: 'low',
    title: 'Structure repaired',
    detail: 'Reclaim above the distribution range',
  }),
];
