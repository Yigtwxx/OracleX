/**
 * The rules the four Konumlanma panels agree on.
 *
 * What is worth pinning here is not the arithmetic — it is the handful of
 * places where "no answer" and "zero" are different things, because every one
 * of them is a place a panel could quietly invent a reading the market did not
 * publish.
 */

import { describe, expect, it } from 'vitest';

import type { BistPositioningRow } from './bist-api';
import {
  applyFilter,
  crowdingPoints,
  futuresPoints,
  median,
  quadrantOf,
  rangeBucketOf,
  rangeHistogram,
  sectorAggregates,
  summarise,
} from './bist-positioning';

function row(overrides: Partial<BistPositioningRow> = {}): BistPositioningRow {
  return {
    ticker: 'TEST',
    symbol: 'BIST:TEST',
    name: 'Test A.Ş.',
    sector: 'Sanayi',
    price: 10,
    change_pct: 0.02,
    market_cap: 1_000_000_000,
    free_float_pct: 0.3,
    relative_volume: 1.4,
    range_position: 0.5,
    beta: 1,
    rsi: 55,
    open_interest: 1000,
    open_interest_change: 100,
    crowding: 4.67,
    ...overrides,
  };
}

describe('quadrantOf', () => {
  it('names the four futures reads from open interest against price', () => {
    expect(quadrantOf(row({ open_interest_change: 100, change_pct: 0.02 }))).toBe('long_build');
    expect(quadrantOf(row({ open_interest_change: 100, change_pct: -0.02 }))).toBe('short_build');
    expect(quadrantOf(row({ open_interest_change: -100, change_pct: 0.02 }))).toBe('short_cover');
    expect(quadrantOf(row({ open_interest_change: -100, change_pct: -0.02 }))).toBe(
      'long_liquidation'
    );
  });

  it('refuses a quadrant for a name sitting on an axis', () => {
    // Unmoved open interest says nothing about who opened what, and an unmoved
    // price says nothing about which side paid for it.
    expect(quadrantOf(row({ open_interest_change: 0 }))).toBeNull();
    expect(quadrantOf(row({ change_pct: 0 }))).toBeNull();
  });

  it('refuses a quadrant for a name with no futures at all', () => {
    expect(quadrantOf(row({ open_interest_change: null }))).toBeNull();
    expect(quadrantOf(row({ change_pct: null }))).toBeNull();
  });
});

describe('rangeBucketOf', () => {
  it('puts a name at its own 52-week high in the last bucket, not past the end', () => {
    expect(rangeBucketOf(1, 20)).toBe(19);
    expect(rangeBucketOf(0, 20)).toBe(0);
  });

  it('has no bucket for an unmeasured range', () => {
    expect(rangeBucketOf(null, 20)).toBeNull();
  });
});

describe('rangeHistogram', () => {
  it('returns every bucket, including the empty ones', () => {
    // The distribution's shape is the panel's whole message; dropping empty
    // buckets would close the gaps and flatter the market.
    const buckets = rangeHistogram([], 20);
    expect(buckets).toHaveLength(20);
    expect(buckets.every((bucket) => bucket.count === 0)).toBe(true);
  });

  it('counts each name into the bucket its range position falls in', () => {
    const buckets = rangeHistogram(
      [
        row({ range_position: 0.02 }),
        row({ range_position: 0.07 }),
        row({ range_position: 0.96 }),
        row({ range_position: null }),
      ],
      10
    );
    expect(buckets[0].count).toBe(2);
    expect(buckets[9].count).toBe(1);
    expect(buckets.reduce((sum, bucket) => sum + bucket.count, 0)).toBe(3);
  });

  it('leaves a bucket without a median when nobody in it published an RSI', () => {
    const buckets = rangeHistogram([row({ range_position: 0.5, rsi: null })], 10);
    expect(buckets[5].count).toBe(1);
    expect(buckets[5].medianRsi).toBeNull();
  });
});

describe('sectorAggregates', () => {
  it('leaves out names with no crowding score', () => {
    // A sector whose names all failed the float or volume floors has no unusual
    // activity to show, and a tile for it would be a claim nothing supports.
    const aggregates = sectorAggregates([
      row({ sector: 'Bankacılık', crowding: null }),
      row({ sector: 'Sanayi', crowding: 3 }),
    ]);
    expect(aggregates.map((entry) => entry.sector)).toEqual(['Sanayi']);
  });

  it('sums crowding per sector and ranks the heaviest first', () => {
    const aggregates = sectorAggregates([
      row({ sector: 'Sanayi', crowding: 2 }),
      row({ sector: 'Bankacılık', crowding: 5 }),
      row({ sector: 'Sanayi', crowding: 4 }),
    ]);
    expect(aggregates[0]).toMatchObject({ sector: 'Sanayi', crowding: 6, count: 2 });
    expect(aggregates[1]).toMatchObject({ sector: 'Bankacılık', crowding: 5, count: 1 });
  });

  it('files a name with no sector under Diğer rather than under an empty label', () => {
    expect(sectorAggregates([row({ sector: '', crowding: 1 })])[0].sector).toBe('Diğer');
  });
});

describe('applyFilter', () => {
  const rows = [
    row({ ticker: 'AAA', sector: 'Bankacılık', open_interest_change: 100, change_pct: 0.02 }),
    row({ ticker: 'BBB', sector: 'Sanayi', open_interest_change: -100, change_pct: 0.02 }),
    row({ ticker: 'CCC', sector: 'Bankacılık', open_interest_change: null, change_pct: 0.02 }),
  ];

  it('selects the whole board when nothing is filtered', () => {
    expect(applyFilter(rows, {})).toHaveLength(3);
  });

  it('combines clauses with AND', () => {
    const selected = applyFilter(rows, { sector: 'Bankacılık', quadrant: 'long_build' });
    expect(selected.map((entry) => entry.ticker)).toEqual(['AAA']);
  });

  it('excludes a name that cannot answer the clause rather than admitting it', () => {
    // CCC has no futures. "Show me the long-build names" must not hand back the
    // names that never had a position to build.
    const selected = applyFilter(rows, { quadrant: 'long_build' });
    expect(selected.map((entry) => entry.ticker)).toEqual(['AAA']);
  });

  it('filters by range bucket', () => {
    const selected = applyFilter(
      [row({ ticker: 'LOW', range_position: 0.01 }), row({ ticker: 'HIGH', range_position: 0.99 })],
      { rangeBucket: 19 },
      20
    );
    expect(selected.map((entry) => entry.ticker)).toEqual(['HIGH']);
  });
});

describe('summarise', () => {
  it('counts the names sitting within a tenth of either 52-week extreme', () => {
    const summary = summarise(
      [
        row({ range_position: 0.95 }),
        row({ range_position: 0.9 }),
        row({ range_position: 0.05 }),
        row({ range_position: 0.5 }),
        row({ range_position: null }),
      ],
      []
    );
    expect(summary.nearHigh).toBe(2);
    expect(summary.nearLow).toBe(1);
  });

  it('counts only the names with a measurable crowding score', () => {
    const summary = summarise([row({ crowding: 3 }), row({ crowding: null })], []);
    expect(summary.scored).toBe(1);
  });

  it('measures open interest growth against yesterday’s book, not today’s', () => {
    // 1000 outstanding after a rise of 100 means the book was 900, so this is a
    // ninth of growth. Dividing by today's 1000 would report a tenth and would
    // understate every build for the same reason it overstates every unwind.
    const summary = summarise([], [row({ open_interest: 1000, open_interest_change: 100 })]);
    expect(summary.openInterestGrowth).toBeCloseTo(100 / 900);
  });

  it('has no open interest reading when the futures board is empty', () => {
    expect(summarise([row()], []).openInterestGrowth).toBeNull();
  });

  it('names no dominant quadrant when two of them tie', () => {
    const summary = summarise(
      [],
      [
        row({ open_interest_change: 100, change_pct: 0.02 }),
        row({ open_interest_change: -100, change_pct: -0.02 }),
      ]
    );
    expect(summary.dominantQuadrant).toBeNull();
  });

  it('names the quadrant holding the most contracts', () => {
    const summary = summarise(
      [],
      [
        row({ open_interest_change: 100, change_pct: 0.02 }),
        row({ open_interest_change: 100, change_pct: 0.03 }),
        row({ open_interest_change: -100, change_pct: -0.02 }),
      ]
    );
    expect(summary.dominantQuadrant).toBe('long_build');
  });
});

describe('crowdingPoints', () => {
  it('drops a name the logarithmic axis cannot place', () => {
    // A zero or missing free float has no position on a log scale, and pinning
    // it to the origin would land it in the very corner the panel exists to
    // draw the eye to.
    const points = crowdingPoints([
      row({ ticker: 'OK' }),
      row({ ticker: 'NOFLOAT', free_float_pct: null }),
      row({ ticker: 'ZERO', free_float_pct: 0 }),
      row({ ticker: 'NOVOL', relative_volume: null }),
    ]);
    expect(points.map((point) => point.ticker)).toEqual(['OK']);
  });
});

describe('futuresPoints', () => {
  it('measures the open interest move against yesterday’s book', () => {
    // Contract counts are not comparable between underlyings — one name's book
    // is fourteen million and another's is one — so the chart needs the ratio.
    const [point] = futuresPoints([
      row({ open_interest: 1000, open_interest_change: 100, change_pct: 0.02 }),
    ]);
    expect(point.openInterestChangeRatio).toBeCloseTo(100 / 900);
  });

  it('has no ratio when yesterday’s book was empty', () => {
    const [point] = futuresPoints([
      row({ open_interest: 100, open_interest_change: 100, change_pct: 0.02 }),
    ]);
    expect(point.openInterestChangeRatio).toBeNull();
  });
});

describe('median', () => {
  it('averages the two middles on an even count', () => {
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });

  it('reads the middle on an odd count, whatever order it arrived in', () => {
    expect(median([9, 1, 5])).toBe(5);
  });

  it('has no median for an empty set', () => {
    expect(median([])).toBeNull();
  });
});
