/**
 * Derivations behind the VİOP margin band chart.
 *
 * The two layers on that page are drawn on one shared price axis, and most of
 * what can go wrong is silent: a book summed across columns instead of read
 * from one, a wall reported at bin zero because nothing qualified, a profile
 * indexed against a grid the book does not share. None of those look wrong on
 * screen — they look like a market.
 */

import { describe, expect, it } from 'vitest';

import type { ViopMarginCell, ViopVolumeProfile } from '@/lib/bist-api';
import {
  gridsAgree,
  nearestWall,
  pointOfControl,
  sideTotals,
  standingBook,
  valueArea,
} from '@/lib/viop-map';

function cell(column: number, bin: number, longTry: number, shortTry: number): ViopMarginCell {
  return [column, bin, longTry, shortTry];
}

function profile(bins: number[]): ViopVolumeProfile {
  return {
    bins,
    total: bins.reduce((sum, value) => sum + value, 0),
    bars: bins.length,
    interval: '60m',
    from: '2026-03-02',
    to: '2026-08-28',
  };
}

describe('pointOfControl', () => {
  it('finds the heaviest bin', () => {
    expect(pointOfControl([1, 5, 3])).toBe(1);
  });

  it('breaks a tie toward the lower bin, and does so stably', () => {
    // Arbitrary but fixed: an unstable tie-break would move the marker between
    // renders of identical data.
    expect(pointOfControl([4, 4, 1])).toBe(0);
    expect(pointOfControl([4, 4, 1])).toBe(0);
  });

  it('is null when nothing traded', () => {
    expect(pointOfControl([0, 0, 0])).toBeNull();
    expect(pointOfControl([])).toBeNull();
  });
});

describe('valueArea', () => {
  it('grows outward from the point of control', () => {
    const area = valueArea([1, 1, 10, 1, 1], 0.7);
    expect(area).toEqual({ low: 2, high: 2 });
  });

  it('takes the heavier neighbour first', () => {
    // Total 19, target 16.15. From the peak: +5 on the right (15), then +2 on
    // the left (17) clears it. The right side is taken first because it is the
    // heavier neighbour, which is the whole rule.
    const area = valueArea([1, 2, 10, 5, 1], 0.85);
    expect(area).toEqual({ low: 1, high: 3 });
  });

  it('stops at the edges rather than running off them', () => {
    const area = valueArea([5, 5, 5], 1);
    expect(area).toEqual({ low: 0, high: 2 });
  });

  it('is null when there is no volume to describe', () => {
    expect(valueArea([0, 0, 0])).toBeNull();
  });
});

describe('standingBook', () => {
  it('reads one column out of the field', () => {
    // Each column is already a complete snapshot, so summing across them would
    // count the same standing position once per session it survived.
    const cells = [cell(8, 3, 100, 0), cell(9, 4, 200, 0)];
    const book = standingBook(cells, 9, 6);
    expect(book.long[3]).toBe(0);
    expect(book.long[4]).toBe(200);
  });

  it('keeps the two sides apart', () => {
    const book = standingBook([cell(9, 2, 100, 50)], 9, 4);
    expect(book.long[2]).toBe(100);
    expect(book.short[2]).toBe(50);
  });

  it('ignores a bin outside the grid rather than throwing', () => {
    const book = standingBook([cell(9, 99, 100, 0)], 9, 4);
    expect(book.long.every((value) => value === 0)).toBe(true);
  });
});

describe('sideTotals', () => {
  it('sums each side within one column', () => {
    const cells = [cell(1, 0, 10, 0), cell(1, 1, 0, 4), cell(1, 2, 6, 0), cell(2, 0, 999, 999)];
    expect(sideTotals(cells, 1)).toEqual({ long: 16, short: 4 });
  });

  it('is zero on both sides for a column with nothing standing', () => {
    expect(sideTotals([], 0)).toEqual({ long: 0, short: 0 });
  });
});

describe('nearestWall', () => {
  it('walks down from spot for longs', () => {
    // Longs are called below the price that opened them.
    expect(nearestWall([5, 0, 90, 0, 0], 4, -1, 10)).toBe(2);
  });

  it('walks up from spot for shorts', () => {
    expect(nearestWall([0, 0, 0, 80, 0], 1, 1, 10)).toBe(3);
  });

  it('is null when nothing clears the threshold', () => {
    // Not bin zero. Zero is a real price on this axis, and returning it would
    // put a wall at the bottom of the chart the data never claimed.
    expect(nearestWall([1, 1, 1, 1], 3, -1, 100)).toBeNull();
  });

  it('does not count the bin spot is already in', () => {
    expect(nearestWall([0, 0, 500, 0], 2, -1, 10)).toBeNull();
  });
});

describe('gridsAgree', () => {
  it('holds when the profile indexes the same grid as the book', () => {
    expect(gridsAgree(profile(new Array(120).fill(1)), 120)).toBe(true);
  });

  it('fails when the two were computed against different grids', () => {
    // The failure this catches is invisible by eye: every volume bar would sit
    // beside a price it does not belong to.
    expect(gridsAgree(profile(new Array(60).fill(1)), 120)).toBe(false);
  });

  it('holds when there is no profile at all', () => {
    // Yahoo's intraday history is allowed to be missing; the map still draws.
    expect(gridsAgree(null, 120)).toBe(true);
  });
});
