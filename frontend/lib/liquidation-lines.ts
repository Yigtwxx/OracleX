import type { LiquidationLine } from './api';

/**
 * Pure logic for the liquidation *levels* view.
 *
 * The chart draws one span per modelled level, and the two questions it asks of
 * every span — which leverage band is this, and how hard should it be drawn —
 * are both cheap enough to answer per frame but wrong in ways that would be
 * invisible on a canvas. They live here so they can be tested.
 */

/** Field positions in the backend's packed span tuple. */
export const START = 0;
export const END = 1;
export const BIN = 2;
export const LEVERAGE = 3;
export const SIDE = 4;
export const NOTIONAL = 5;

export type LeverageBucket = 'low' | 'medium' | 'high';

export const BUCKETS: LeverageBucket[] = ['high', 'medium', 'low'];

/**
 * Thresholds rather than an explicit tier list.
 *
 * The backend owns `LEVERAGE_TIERS` and is free to add a band. Matching on
 * ranges means a new tier lands in a sensible bucket on its own, where an
 * exhaustive map would silently drop it from every filter.
 */
const MEDIUM_FROM = 25;
const HIGH_FROM = 50;

export function leverageBucket(leverage: number): LeverageBucket {
  if (leverage >= HIGH_FROM) return 'high';
  if (leverage >= MEDIUM_FROM) return 'medium';
  return 'low';
}

export function filterLines(
  lines: LiquidationLine[],
  enabled: ReadonlySet<LeverageBucket>
): LiquidationLine[] {
  // All three on is the common case and the most expensive to filter, so skip
  // the pass entirely rather than rebuilding an identical array every render.
  if (enabled.size === BUCKETS.length) return lines;
  return lines.filter((line) => enabled.has(leverageBucket(line[LEVERAGE])));
}

/**
 * The largest span in a payload, which is what the bubble radii are scaled to.
 *
 * Taken over the *unfiltered* set on purpose. Rescaling to whatever survives the
 * leverage filter would redraw every remaining bubble larger the moment a band
 * is switched off, which reads as the market having moved.
 */
export function maxNotional(lines: LiquidationLine[]): number {
  let max = 0;
  for (const line of lines) if (line[NOTIONAL] > max) max = line[NOTIONAL];
  return max;
}

/**
 * How many levels get a bubble.
 *
 * The reference chart draws one per level, which works because its book is
 * sparse; ours resolves ten leverage tiers over 240 bars and answers with more
 * than a thousand spans, and a thousand discs is a fog with a chart somewhere
 * behind it. Marking only the heaviest keeps the bubble meaning what it should
 * — *this* is where size actually sits — and leaves the spans readable.
 */
export const BUBBLE_LIMIT = 60;

/**
 * The `limit` heaviest spans, largest first.
 *
 * Selected from what the leverage filter left rather than from the whole book,
 * so switching a band off promotes the next levels down instead of emptying the
 * chart of marks.
 */
export function topByNotional(lines: LiquidationLine[], limit: number): LiquidationLine[] {
  return [...lines].sort((a, b) => b[NOTIONAL] - a[NOTIONAL]).slice(0, limit);
}

/** Pixel radius bounds for the origin bubbles. */
const MIN_RADIUS = 3;
const MAX_RADIUS = 14;

/**
 * How large the bubble marking where a level was created is drawn.
 *
 * Square-rooted so that *area* tracks notional rather than radius: a level
 * holding four times as much draws twice as wide, which is how a reader
 * actually compares two discs. Scaling the radius linearly would make the top
 * of the book look an order of magnitude heavier than it is.
 *
 * The floor matters because only the top of the book is drawn: the smallest
 * bubble on screen is still a real cluster, and shrinking it to a pixel would
 * say the opposite.
 */
export function bubbleRadius(notional: number, largest: number): number {
  if (largest <= 0) return MIN_RADIUS;
  const share = Math.min(Math.max(notional, 0) / largest, 1);
  return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(share);
}

/** Exponent on the opacity ramp; > 1 keeps faint spans close to the background. */
const ALPHA_CURVE = 1.6;
const MIN_ALPHA = 0.12;

/**
 * How strongly one span is drawn, as a share of its *own* tier's peak.
 *
 * Normalising globally would be wrong rather than merely unflattering: the 100x
 * band's largest span is around 0.4x the 10x band's, because it carries less
 * weight and is swept before it can accumulate. Scaled against the global peak
 * the whole band renders under 40% opacity, so switching the filter to
 * high-leverage-only would look like a rendering fault.
 */
export function lineAlpha(notional: number, tierMax: number): number {
  if (tierMax <= 0) return MIN_ALPHA;
  const share = Math.min(notional / tierMax, 1);
  return MIN_ALPHA + (1 - MIN_ALPHA) * Math.pow(share, ALPHA_CURVE);
}
