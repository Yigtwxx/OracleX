import type { LiquidationProfileLevel } from './api';

/**
 * Pure logic for the liquidation *profile* view.
 *
 * The payload is a sparse `[bin, tier, side, notional]` list; the chart needs
 * one dense series per leverage tier and two cumulative curves. Both are
 * derivations rather than data, which is why they are here and not on the wire:
 * the cumulative curves in particular are a few kilobytes the client can
 * compute in a pass, and shipping them would put a second copy of the same book
 * in the payload for the two to disagree over.
 */

/** Field positions in the backend's packed level tuple. */
export const BIN = 0;
export const TIER = 1;
export const SIDE = 2;
export const NOTIONAL = 3;

export const LONG = 0;
export const SHORT = 1;

/** Centre price of each bin, which is what the model's numbers are attached to. */
export function binPrices(bins: number, priceMin: number, binSize: number): number[] {
  return Array.from({ length: bins }, (_, bin) => priceMin + (bin + 0.5) * binSize);
}

/** The bin spot sits in, clamped so a price at either edge still lands inside. */
export function spotBin(price: number, priceMin: number, binSize: number, bins: number): number {
  if (binSize <= 0) return 0;
  return Math.min(Math.max(Math.floor((price - priceMin) / binSize), 0), bins - 1);
}

/**
 * `[tier][bin]` notional, summed back over the two sides.
 *
 * Summing is safe because a bin holds one side or the other: a long liquidates
 * below the price that opened it and a short above, so the two only meet if
 * spot has crossed the level since — in which case the level is gone. Keeping
 * them apart would mean eight stacked segments per bar to say what four say.
 */
export function stackByTier(
  levels: LiquidationProfileLevel[],
  bins: number,
  tierCount: number
): number[][] {
  const stack = Array.from({ length: tierCount }, () => new Array<number>(bins).fill(0));
  for (const level of levels) {
    const tier = stack[level[TIER]];
    if (tier) tier[level[BIN]] += level[NOTIONAL];
  }
  return stack;
}

/**
 * What would be liquidated if price walked from spot out to each bin.
 *
 * Read outward from spot in both directions, so `long[b]` is every long between
 * bin `b` and spot — the notional a fall to that price would take out — and
 * `short[b]` the same going up. Each side is `null` on the other side of spot
 * rather than zero: a flat line along the axis reads as "measured, and there is
 * nothing here", which is the opposite of what it means.
 */
export function cumulativeFromSpot(
  levels: LiquidationProfileLevel[],
  bins: number,
  spot: number
): { long: (number | null)[]; short: (number | null)[] } {
  const perBin = { long: new Array<number>(bins).fill(0), short: new Array<number>(bins).fill(0) };
  for (const level of levels) {
    const side = level[SIDE] === LONG ? perBin.long : perBin.short;
    side[level[BIN]] += level[NOTIONAL];
  }

  const long = new Array<number | null>(bins).fill(null);
  const short = new Array<number | null>(bins).fill(null);

  let running = 0;
  for (let bin = spot; bin >= 0; bin -= 1) {
    running += perBin.long[bin];
    long[bin] = running;
  }

  running = 0;
  for (let bin = spot; bin < bins; bin += 1) {
    running += perBin.short[bin];
    short[bin] = running;
  }

  return { long, short };
}

/** A price, in the shortest form that still separates two adjacent buckets. */
export function formatBucket(price: number): string {
  return price.toLocaleString('en-US', {
    maximumFractionDigits: price >= 1000 ? 0 : price >= 1 ? 2 : 6,
  });
}
