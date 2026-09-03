import { describe, expect, it } from 'vitest';

import type { LiquidationProfileLevel } from './api';
import {
  binPrices,
  cumulativeFromSpot,
  formatBucket,
  spotBin,
  stackByTier,
} from './liquidation-profile';

/** `[bin, tier, side, notional]`. */
function level(bin: number, tier: number, side: number, notional: number): LiquidationProfileLevel {
  return [bin, tier, side, notional];
}

describe('binPrices', () => {
  it('returns bin centres, not edges', () => {
    expect(binPrices(3, 100, 10)).toEqual([105, 115, 125]);
  });
});

describe('spotBin', () => {
  it('finds the bin a price sits in', () => {
    expect(spotBin(126, 100, 10, 3)).toBe(2);
  });

  it('clamps a price above the grid rather than indexing past it', () => {
    expect(spotBin(9_999, 100, 10, 3)).toBe(2);
  });

  it('clamps a price below the grid', () => {
    expect(spotBin(1, 100, 10, 3)).toBe(0);
  });

  it('survives a zero-width grid', () => {
    expect(spotBin(100, 100, 0, 3)).toBe(0);
  });
});

describe('stackByTier', () => {
  it('sums both sides into one bar per bin', () => {
    const stack = stackByTier([level(1, 0, 0, 100), level(1, 0, 1, 50)], 3, 2);
    expect(stack[0]).toEqual([0, 150, 0]);
    expect(stack[1]).toEqual([0, 0, 0]);
  });

  it('keeps tiers apart', () => {
    const stack = stackByTier([level(0, 0, 0, 10), level(0, 1, 0, 20)], 1, 2);
    expect(stack).toEqual([[10], [20]]);
  });

  it('ignores a tier the payload knows about and the client does not', () => {
    // A backend that adds a tier must not throw a client that has not caught up.
    expect(() => stackByTier([level(0, 9, 0, 10)], 1, 2)).not.toThrow();
  });
});

describe('cumulativeFromSpot', () => {
  const levels = [
    level(0, 0, 0, 100), // long, far below spot
    level(1, 0, 0, 50), // long, just below spot
    level(3, 0, 1, 70), // short, just above spot
    level(4, 0, 1, 30), // short, far above spot
  ];

  it('accumulates longs downward from spot', () => {
    const { long } = cumulativeFromSpot(levels, 5, 2);
    // Reading down: nothing at spot, then 50, then 150.
    expect(long[2]).toBe(0);
    expect(long[1]).toBe(50);
    expect(long[0]).toBe(150);
  });

  it('accumulates shorts upward from spot', () => {
    const { short } = cumulativeFromSpot(levels, 5, 2);
    expect(short[2]).toBe(0);
    expect(short[3]).toBe(70);
    expect(short[4]).toBe(100);
  });

  it('leaves each side blank past spot rather than drawing a zero', () => {
    // A line resting on the axis would claim the far side was measured and
    // found empty, which is not what a one-sided curve means.
    const { long, short } = cumulativeFromSpot(levels, 5, 2);
    expect(long.slice(3)).toEqual([null, null]);
    expect(short.slice(0, 2)).toEqual([null, null]);
  });

  it('rises monotonically away from spot', () => {
    const { long, short } = cumulativeFromSpot(levels, 5, 2);
    expect(long[0]!).toBeGreaterThanOrEqual(long[1]!);
    expect(short[4]!).toBeGreaterThanOrEqual(short[3]!);
  });

  it('ends at the totals it is built from', () => {
    const { long, short } = cumulativeFromSpot(levels, 5, 2);
    expect(long[0]).toBe(150);
    expect(short[4]).toBe(100);
  });
});

describe('formatBucket', () => {
  it('drops decimals on a price where they carry nothing', () => {
    expect(formatBucket(79_053.4)).toBe('79,053');
  });

  it('keeps them where a bucket is narrower than a dollar', () => {
    expect(formatBucket(2.345)).toBe('2.35');
  });

  it('keeps enough of them for a sub-cent asset', () => {
    expect(formatBucket(0.0001234)).toBe('0.000123');
  });
});
