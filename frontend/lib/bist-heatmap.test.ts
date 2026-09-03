/**
 * The BIST heatmap's scales and derivations.
 *
 * The first test in here is the reason the file exists. The payload speaks in
 * fractions and the scales are written in percent, so exactly one multiplication
 * stands between them — and getting it wrong produces a valid number, a
 * coloured tile and no error at all. Everything else is the same class of
 * problem: a board that loses a company, or paints a missing reading as a
 * measured zero, looks entirely correct on screen.
 */

import { describe, expect, it } from 'vitest';

import type { BistHeatmapSector, BistHeatmapTile } from '@/lib/bist-api';
import {
  BIST_CHANGE_SCALE,
  BIST_METRIC_CONFIG,
  BIST_OI_SCALE,
  BIST_TURNOVER_SCALE,
  bucketForTile,
  groupBySector,
  metricIsEmpty,
  metricValue,
  oiBadge,
  tileDescription,
  type BistHeatMetric,
} from '@/lib/bist-heatmap';
import { UNKNOWN_BUCKET, type HeatBucket } from '@/lib/heatmap-scale';

function tile(overrides: Partial<BistHeatmapTile> = {}): BistHeatmapTile {
  return {
    ticker: 'THYAO',
    symbol: 'BIST:THYAO',
    name: 'Türk Hava Yolları A.O.',
    sector: 'Ulaştırma',
    price: 304.5,
    change_pct: 0.024,
    traded_value: 4.2e9,
    volume: 1.38e7,
    market_cap: 4.2e11,
    indices: ['XU100', 'XU030'],
    has_futures: true,
    contracts: 3,
    open_interest: 148_320,
    open_interest_change: 6120,
    open_interest_change_pct: 0.043,
    ...overrides,
  };
}

function sector(overrides: Partial<BistHeatmapSector> = {}): BistHeatmapSector {
  return {
    sector: 'Ulaştırma',
    count: 1,
    market_cap: 4.2e11,
    weight: 1,
    change_pct: 0.024,
    advancers: 1,
    decliners: 0,
    ...overrides,
  };
}

function labelFor(bucket: HeatBucket): string {
  return bucket.label;
}

describe('metricValue — the fraction/percent boundary', () => {
  it('reads a 2.4% day as 2.4, not 240', () => {
    // The whole point of the file. `0.024 * 100 * 100` is 240, which is a
    // perfectly valid number that lands in the brightest bucket and throws
    // nothing on the way there.
    expect(metricValue(tile({ change_pct: 0.024 }), 'change')).toBeCloseTo(2.4);
    expect(bucketForTile(tile({ change_pct: 0.024 }), 'change')).toBe(BIST_CHANGE_SCALE[2]);
  });

  it('leaves turnover in lira — its scale is written in lira', () => {
    expect(metricValue(tile({ traded_value: 4.2e9 }), 'traded_value')).toBe(4.2e9);
    expect(bucketForTile(tile({ traded_value: 4.2e9 }), 'traded_value')).toBe(
      BIST_TURNOVER_SCALE[0]
    );
    // A mid-board name, to pin that the bounds are read as lira rather than as
    // some scaled multiple of them.
    expect(bucketForTile(tile({ traded_value: 3e8 }), 'traded_value')).toBe(
      BIST_TURNOVER_SCALE[2]
    );
  });

  it('converts open interest change and keeps its sign', () => {
    expect(metricValue(tile({ open_interest_change_pct: -0.13 }), 'open_interest')).toBeCloseTo(
      -13
    );
    expect(bucketForTile(tile({ open_interest_change_pct: -0.13 }), 'open_interest')).toBe(
      BIST_OI_SCALE[5]
    );
  });

  it('turns a missing reading into unknown, never into zero', () => {
    expect(metricValue(tile({ change_pct: null }), 'change')).toBeUndefined();
    expect(bucketForTile(tile({ change_pct: null }), 'change')).toBe(UNKNOWN_BUCKET);
    expect(bucketForTile(tile({ open_interest_change_pct: null }), 'open_interest')).toBe(
      UNKNOWN_BUCKET
    );
  });

  it('does not confuse a real zero with a missing one', () => {
    expect(metricValue(tile({ change_pct: 0 }), 'change')).toBe(0);
    expect(bucketForTile(tile({ change_pct: 0 }), 'change')).toBe(BIST_CHANGE_SCALE[3]);
  });
});

describe('scale invariants', () => {
  const scales: [string, readonly HeatBucket[]][] = [
    ['change', BIST_CHANGE_SCALE],
    ['turnover', BIST_TURNOVER_SCALE],
    ['open interest', BIST_OI_SCALE],
  ];

  describe.each(scales)('%s', (_name, scale) => {
    it('is ordered high to low', () => {
      const bounds = scale.map((bucket) => bucket.min);
      expect([...bounds].sort((a, b) => b - a)).toEqual(bounds);
    });

    it('ends at -Infinity so every real number matches', () => {
      expect(scale[scale.length - 1].min).toBe(Number.NEGATIVE_INFINITY);
    });

    it('declares exactly one ink class per bucket', () => {
      for (const bucket of scale) {
        const light = bucket.className.includes('text-fg');
        const dark = bucket.className.includes('text-bg');
        expect(light !== dark).toBe(true);
      }
    });

    it('flips the brightest stop to the background ink', () => {
      expect(scale[0].className).toContain('text-bg');
    });

    it('labels every bucket distinctly', () => {
      const labels = scale.map(labelFor);
      expect(new Set(labels).size).toBe(labels.length);
    });

    it('never reuses the unknown swatch', () => {
      expect(scale.map((bucket) => bucket.className)).not.toContain(UNKNOWN_BUCKET.className);
    });
  });
});

describe('unknownWithoutFutures', () => {
  const noFutures = tile({
    has_futures: false,
    contracts: 0,
    open_interest: null,
    open_interest_change: null,
    open_interest_change_pct: null,
  });

  it('dims a name without contracts on the open-interest metric', () => {
    expect(bucketForTile(noFutures, 'open_interest')).toBe(UNKNOWN_BUCKET);
  });

  it('leaves the same name fully coloured on price and turnover', () => {
    // Having no futures says nothing about how a stock moved. Dimming half the
    // board for it would invent a distinction the metric does not carry.
    expect(bucketForTile(noFutures, 'change')).toBe(BIST_CHANGE_SCALE[2]);
    expect(bucketForTile(noFutures, 'traded_value')).toBe(BIST_TURNOVER_SCALE[0]);
  });
});

describe('metricIsEmpty', () => {
  it('is true only when no tile has a reading', () => {
    expect(metricIsEmpty([tile({ change_pct: null }), tile({ change_pct: null })], 'change')).toBe(
      true
    );
    expect(metricIsEmpty([tile({ change_pct: null }), tile()], 'change')).toBe(false);
  });
});

describe('groupBySector', () => {
  it('keeps the server ranking and drops nothing', () => {
    const tiles = [
      tile({ ticker: 'THYAO', sector: 'Ulaştırma' }),
      tile({ ticker: 'AKBNK', sector: 'Bankacılık' }),
      tile({ ticker: 'GARAN', sector: 'Bankacılık' }),
    ];
    const groups = groupBySector(tiles, [
      sector({ sector: 'Bankacılık', count: 2 }),
      sector({ sector: 'Ulaştırma', count: 1 }),
    ]);

    expect(groups.map((group) => group.sector.sector)).toEqual(['Bankacılık', 'Ulaştırma']);
    expect(groups.reduce((total, group) => total + group.tiles.length, 0)).toBe(tiles.length);
  });

  it('draws a tile whose sector the payload does not carry', () => {
    const groups = groupBySector([tile({ sector: 'Sınıflandırılmamış' })], [sector()]);

    expect(groups).toHaveLength(1);
    expect(groups[0].sector.sector).toBe('Sınıflandırılmamış');
    expect(groups[0].tiles).toHaveLength(1);
  });

  it('omits a sector row with no tiles behind it', () => {
    // `limit` truncates tiles but not the statistics, so the payload can name a
    // sector none of the drawn tiles belong to. An empty section is noise.
    const groups = groupBySector(
      [tile({ sector: 'Ulaştırma' })],
      [sector({ sector: 'Ulaştırma' }), sector({ sector: 'Bankacılık' })]
    );

    expect(groups.map((group) => group.sector.sector)).toEqual(['Ulaştırma']);
  });
});

describe('oiBadge', () => {
  it('is absent for a name with no contracts', () => {
    expect(oiBadge(tile({ has_futures: false, open_interest: null }))).toBeNull();
  });

  it('still appears when the position did not move', () => {
    // A position that held is a reading. Blanking it would make it look like
    // there are no futures on the name at all.
    const badge = oiBadge(tile({ open_interest_change: null, open_interest_change_pct: null }));

    expect(badge).not.toBeNull();
    expect(badge?.text).toContain('·');
  });

  it('points the arrow the way the position moved', () => {
    expect(oiBadge(tile({ open_interest_change: 6120 }))?.text).toContain('▲');
    expect(oiBadge(tile({ open_interest_change: -6120 }))?.text).toContain('▼');
  });
});

describe('tileDescription', () => {
  it('names the company, the metric and the futures state', () => {
    const description = tileDescription(tile(), 'change');

    expect(description).toContain('THYAO');
    expect(description).toContain(BIST_METRIC_CONFIG.change.label);
    expect(description).toContain('VİOP');
  });

  it('says so when there are no futures', () => {
    expect(tileDescription(tile({ has_futures: false }), 'change')).toContain('VİOP kontratı yok');
  });
});

describe('BIST_METRIC_CONFIG', () => {
  const metrics: BistHeatMetric[] = ['change', 'traded_value', 'open_interest'];

  it.each(metrics)('%s prints a real unit rather than a bucket bound', (metric) => {
    const printed = BIST_METRIC_CONFIG[metric].display(tile());
    expect(printed).not.toBe('');
    expect(printed).not.toContain('Infinity');
  });
});
