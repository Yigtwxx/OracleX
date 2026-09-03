/**
 * Pure derivations for the VİOP margin scan band map.
 *
 * Here rather than in the chart component because the vitest config only
 * collects the test files under `lib/`, and every rule below is one a wrong
 * answer would hide: a book summed from the wrong spans, a point of control
 * picked off the wrong array, a wall reported where there is none.
 *
 * The packed cell tuple is the wire format: `[column, bin, longTry, shortTry]`.
 * Positions rather than field names because the payload carries thousands of
 * them and the grid they index is sent once.
 */

import type { ViopMarginCell, ViopVolumeProfile } from '@/lib/bist-api';
import { binPrices, spotBin } from '@/lib/liquidation-profile';

export { binPrices, spotBin };

/** Field positions in the packed cell tuple. */
export const COLUMN = 0;
export const BIN = 1;
export const LONG_TRY = 2;
export const SHORT_TRY = 3;

/**
 * The bin holding the most volume, or null when nothing traded.
 *
 * Ties resolve to the lowest bin, which is arbitrary but fixed — an unstable
 * tie-break would move the marker between renders of identical data.
 */
export function pointOfControl(bins: readonly number[]): number | null {
  let best: number | null = null;
  let peak = 0;
  for (let index = 0; index < bins.length; index += 1) {
    if (bins[index] > peak) {
      peak = bins[index];
      best = index;
    }
  }
  return best;
}

/**
 * The contiguous band around the point of control holding `share` of volume.
 *
 * Grown outward one bin at a time, always taking the heavier neighbour, which
 * is the standard construction. Returns null when there is no volume to
 * describe rather than an empty range at bin zero.
 */
export function valueArea(
  bins: readonly number[],
  share: number = 0.7
): { low: number; high: number } | null {
  const poc = pointOfControl(bins);
  if (poc === null) return null;

  const total = bins.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return null;

  const target = total * share;
  let low = poc;
  let high = poc;
  let held = bins[poc];

  while (held < target && (low > 0 || high < bins.length - 1)) {
    const below = low > 0 ? bins[low - 1] : -1;
    const above = high < bins.length - 1 ? bins[high + 1] : -1;
    if (above >= below) {
      high += 1;
      held += bins[high];
    } else {
      low -= 1;
      held += bins[low];
    }
  }
  return { low, high };
}

/**
 * The book as it stood at `column`, per bin and side.
 *
 * Reading one column out of the field rather than accumulating across it: each
 * column is already a complete snapshot, so summing several would count the
 * same standing position once per session it survived.
 */
export function standingBook(
  cells: readonly ViopMarginCell[],
  column: number,
  bins: number
): { long: number[]; short: number[] } {
  const long = new Array<number>(bins).fill(0);
  const short = new Array<number>(bins).fill(0);
  for (const cell of cells) {
    if (cell[COLUMN] !== column) continue;
    const bin = cell[BIN];
    if (bin < 0 || bin >= bins) continue;
    long[bin] += cell[LONG_TRY];
    short[bin] += cell[SHORT_TRY];
  }
  return { long, short };
}

/** Notional on each side in one column of the field. */
export function sideTotals(
  cells: readonly ViopMarginCell[],
  column: number
): { long: number; short: number } {
  let long = 0;
  let short = 0;
  for (const cell of cells) {
    if (cell[COLUMN] !== column) continue;
    long += cell[LONG_TRY];
    short += cell[SHORT_TRY];
  }
  return { long, short };
}

/**
 * The nearest bin to spot whose standing book clears `threshold`, or null.
 *
 * `direction` is -1 to walk down from spot and 1 to walk up, which is where
 * the two sides sit: a long is called below the price that opened it.
 *
 * Null rather than bin zero when nothing qualifies: zero is a real price on
 * this axis, and returning it would put a wall at the bottom of the chart that
 * the data never claimed.
 */
export function nearestWall(
  book: readonly number[],
  spot: number,
  direction: -1 | 1,
  threshold: number
): number | null {
  const step = direction;
  for (let index = spot + step; index >= 0 && index < book.length; index += step) {
    if (book[index] >= threshold) return index;
  }
  return null;
}

/**
 * Whether the two layers were computed against the same grid.
 *
 * The profile and the book are drawn on one shared axis, so a length mismatch
 * means one of them is indexed against a grid the other does not share — every
 * bar would sit at a price it does not belong to. Cheap to check, and the
 * failure it catches is invisible by eye.
 */
export function gridsAgree(profile: ViopVolumeProfile | null, bins: number): boolean {
  return profile === null || profile.bins.length === bins;
}
