import { describe, expect, it } from 'vitest';
import { CoinData } from './api';
import { changeHistogram, computeBreadth, findDivergences, inBucket } from './market-breadth';

/** Only the fields these derivations read; the rest of CoinData is inert here. */
const coin = (over: Partial<CoinData> & { symbol: string }): CoinData => ({
  name: over.symbol,
  logo: '',
  price: 100,
  change_24h: 0,
  volume_24h: 10_000_000,
  high_24h: 110,
  low_24h: 90,
  market_cap: 1_000_000_000,
  market_cap_rank: 1,
  ...over,
});

describe('computeBreadth', () => {
  it('splits the universe into advancing, declining and unchanged', () => {
    const summary = computeBreadth([
      coin({ symbol: 'A', change_24h: 2 }),
      coin({ symbol: 'B', change_24h: 5 }),
      coin({ symbol: 'C', change_24h: -3 }),
      coin({ symbol: 'D', change_24h: 0 }),
    ]);

    expect(summary.advancing).toBe(2);
    expect(summary.declining).toBe(1);
    expect(summary.unchanged).toBe(1);
    expect(summary.advancingPct).toBe(50);
    expect(summary.advanceDeclineRatio).toBe(2);
  });

  it('reports no ratio when nothing declined, rather than Infinity', () => {
    const summary = computeBreadth([
      coin({ symbol: 'A', change_24h: 1 }),
      coin({ symbol: 'B', change_24h: 2 }),
    ]);

    expect(summary.advanceDeclineRatio).toBeNull();
  });

  it('separates the typical asset from the average one', () => {
    // Four flat assets and one moonshot: the mean says the market is up 4%,
    // the median says the market did nothing. Both are true and the gap is
    // the entire point of showing them together.
    const summary = computeBreadth([
      coin({ symbol: 'A', change_24h: 0.1 }),
      coin({ symbol: 'B', change_24h: 0.1 }),
      coin({ symbol: 'C', change_24h: 0.2 }),
      coin({ symbol: 'D', change_24h: 0.2 }),
      coin({ symbol: 'E', change_24h: 20 }),
    ]);

    expect(summary.medianChange).toBeCloseTo(0.2);
    expect(summary.meanChange).toBeCloseTo(4.12);
  });

  it('weights the cap-weighted change by market cap, not by count', () => {
    const summary = computeBreadth([
      coin({ symbol: 'BIG', change_24h: 1, market_cap: 900 }),
      coin({ symbol: 'SMALL', change_24h: 11, market_cap: 100 }),
    ]);

    // (1*900 + 11*100) / 1000
    expect(summary.capWeightedChange).toBeCloseTo(2);
    expect(summary.meanChange).toBeCloseTo(6);
  });

  it('drops rows missing a market cap from both halves of the weighting', () => {
    const summary = computeBreadth([
      coin({ symbol: 'A', change_24h: 4, market_cap: 100 }),
      coin({ symbol: 'B', change_24h: 100, market_cap: 0 }),
    ]);

    expect(summary.capWeightedChange).toBeCloseTo(4);
  });

  it('places each asset inside its own 24h band', () => {
    const summary = computeBreadth([
      coin({ symbol: 'LOW', low_24h: 0, high_24h: 100, price: 10 }),
      coin({ symbol: 'MID', low_24h: 0, high_24h: 100, price: 50 }),
      coin({ symbol: 'HIGH', low_24h: 0, high_24h: 100, price: 90 }),
    ]);

    expect(summary.medianRangePosition).toBeCloseTo(0.5);
    expect(summary.upperHalfCount).toBe(1);
    expect(summary.rangeReporting).toBe(3);
  });

  it('ignores a degenerate band instead of dividing by zero', () => {
    const summary = computeBreadth([
      coin({ symbol: 'FLAT', low_24h: 100, high_24h: 100, price: 100 }),
      coin({ symbol: 'OK', low_24h: 0, high_24h: 100, price: 25 }),
    ]);

    expect(summary.rangeReporting).toBe(1);
    expect(summary.medianRangePosition).toBeCloseTo(0.25);
  });

  it('surfaces turnover concentrated in a handful of names', () => {
    // Ten small venues and one that reports more than all of them combined —
    // the shape of a broken upstream volume field.
    const coins = [
      coin({ symbol: 'BROKEN', volume_24h: 900 }),
      ...Array.from({ length: 10 }, (_, i) => coin({ symbol: `S${i}`, volume_24h: 10 })),
    ];

    expect(computeBreadth(coins).top10VolumeShare).toBeCloseTo(99);
  });

  it('counts the weekly tape only for assets that report one', () => {
    const summary = computeBreadth([
      coin({ symbol: 'A', change_7d: 5 }),
      coin({ symbol: 'B', change_7d: -5 }),
      coin({ symbol: 'C', change_7d: null }),
    ]);

    expect(summary.reporting7d).toBe(2);
    expect(summary.advancing7d).toBe(1);
  });

  it('reports no weekly reading when nothing carries one', () => {
    const summary = computeBreadth([coin({ symbol: 'A' }), coin({ symbol: 'B' })]);

    expect(summary.advancing7d).toBeNull();
    expect(summary.reporting7d).toBe(0);
  });

  it('survives an empty payload', () => {
    const summary = computeBreadth([]);

    expect(summary.total).toBe(0);
    expect(summary.advancingPct).toBe(0);
    expect(summary.medianChange).toBeNull();
    expect(summary.capWeightedChange).toBeNull();
    expect(summary.top10VolumeShare).toBeNull();
  });
});

describe('changeHistogram', () => {
  it('keeps a fixed axis so the chart can be compared across refreshes', () => {
    const empty = changeHistogram([]);
    const busy = changeHistogram([coin({ symbol: 'A', change_24h: 2 })]);

    expect(empty).toHaveLength(12);
    expect(busy).toHaveLength(12);
    expect(empty.map((b) => b.label)).toEqual(busy.map((b) => b.label));
    expect(empty.every((b) => b.count === 0)).toBe(true);
  });

  it('counts a value landing on an edge exactly once, on the upper side', () => {
    const buckets = changeHistogram([coin({ symbol: 'EDGE', change_24h: 3 })]);
    const hit = buckets.filter((b) => b.count > 0);

    expect(hit).toHaveLength(1);
    expect(hit[0].min).toBe(3);
    expect(hit[0].max).toBe(6);
  });

  it('catches the tails in the open-ended buckets', () => {
    const buckets = changeHistogram([
      coin({ symbol: 'CRASH', change_24h: -80 }),
      coin({ symbol: 'MOON', change_24h: 400 }),
    ]);

    expect(buckets[0].count).toBe(1);
    expect(buckets[0].label).toBe('< -20%');
    expect(buckets[buckets.length - 1].count).toBe(1);
    expect(buckets[buckets.length - 1].label).toBe('> +20%');
  });

  it('totals to the number of assets that reported a change', () => {
    const coins = [
      coin({ symbol: 'A', change_24h: -7 }),
      coin({ symbol: 'B', change_24h: 0 }),
      coin({ symbol: 'C', change_24h: 0.5 }),
      coin({ symbol: 'D', change_24h: 12 }),
    ];

    expect(changeHistogram(coins).reduce((sum, b) => sum + b.count, 0)).toBe(4);
  });

  it('agrees with the predicate the table filters by', () => {
    const coins = [
      coin({ symbol: 'A', change_24h: 0.4 }),
      coin({ symbol: 'B', change_24h: 0.9 }),
      coin({ symbol: 'C', change_24h: 4 }),
    ];
    const bucket = changeHistogram(coins).find((b) => b.min === 0 && b.max === 1)!;

    expect(bucket.count).toBe(2);
    expect(coins.filter((c) => inBucket(c, bucket))).toHaveLength(2);
  });
});

describe('findDivergences', () => {
  const universe = [
    coin({ symbol: 'TURN', change_24h: 6, change_7d: -18 }),
    coin({ symbol: 'TURN2', change_24h: 2, change_7d: -4 }),
    coin({ symbol: 'FADE', change_24h: -7, change_7d: 48 }),
    coin({ symbol: 'FADE2', change_24h: -1, change_7d: 3 }),
    coin({ symbol: 'ALIGNED', change_24h: 5, change_7d: 20 }),
    coin({ symbol: 'DUST', change_24h: 40, change_7d: -60, volume_24h: 500 }),
  ];

  it('splits the day-against-week names into the two directions', () => {
    const { reversing, fading } = findDivergences(universe);

    expect(reversing.map((c) => c.symbol)).toEqual(['TURN', 'TURN2']);
    expect(fading.map((c) => c.symbol)).toEqual(['FADE', 'FADE2']);
  });

  it('excludes illiquid names however large their move', () => {
    expect(findDivergences(universe).reversing.map((c) => c.symbol)).not.toContain('DUST');
    expect(findDivergences(universe, { minVolume: 0 }).reversing[0].symbol).toBe('DUST');
  });

  it('ranks by the size of the contradicting move and respects the limit', () => {
    const { reversing, fading } = findDivergences(universe, { limit: 1 });

    expect(reversing.map((c) => c.symbol)).toEqual(['TURN']);
    expect(fading.map((c) => c.symbol)).toEqual(['FADE']);
  });

  it('skips assets with no weekly reading to contradict', () => {
    const { reversing } = findDivergences([coin({ symbol: 'A', change_24h: 5, change_7d: null })]);

    expect(reversing).toEqual([]);
  });
});
