import { describe, expect, it } from 'vitest';

import type { Ipo, IpoResults, IpoState, IpoStructure } from '@/lib/bist-api';
import {
  absentCopy,
  allocationSegments,
  BUCKET_LABELS,
  calendarLanes,
  histogramReady,
  ipoStateLabel,
  medianReturn,
  MIN_SAMPLE,
  positiveShare,
  proceedsSegments,
  rankByReturn,
  returnBuckets,
  structureSegments,
  undatedRows,
  unmeasuredCount,
} from '@/lib/bist-ipo';

function ipo(overrides: Partial<Ipo> = {}): Ipo {
  return {
    slug: 'acme-a-s',
    url: 'https://halkarz.com/acme-a-s/',
    company: 'Acme A.Ş.',
    ticker: 'ACME',
    state: 'listed',
    is_new: false,
    offer_dates: { start: '2026-02-01', end: '2026-02-02', raw: '1-2 Şubat 2026' },
    listing_date: '2026-02-10',
    price: { low: 50, high: 50, is_band: false, raw: '50,00 TL' },
    lots: 40_000_000,
    free_float_lots: 39_997_279,
    free_float_pct: 0.2499,
    broker: 'Aracı A.Ş.',
    method: 'Eşit Dağıtım',
    market: 'Yıldız Pazar',
    structure: null,
    use_of_proceeds: null,
    proceeds_source: null,
    results: null,
    performance: {
      price: 60,
      nominal: 0.2,
      real: 0.05,
      days_listed: 200,
      seasoned: true,
      market_cap: 1.2e10,
      sector: 'Sanayi',
      measured_at: '2026-09-04T09:00:00Z',
    },
    updated_at: '2026-09-03T17:01',
    unparsed: [],
    ...overrides,
  };
}

function withReturn(nominal: number, real: number | null = nominal - 0.1, slug = `r-${nominal}`) {
  return ipo({
    slug,
    ticker: slug.toUpperCase().slice(0, 5),
    performance: { ...ipo().performance!, nominal, real },
  });
}

describe('rankByReturn', () => {
  it('drops rows with no performance and accounts for them exactly', () => {
    // The assertion that stops an unmeasurable listing being drawn at zero,
    // which reads as one that went nowhere.
    const rows = [withReturn(0.3), ipo({ slug: 'x', performance: null }), withReturn(-0.1)];
    const ranked = rankByReturn(rows, 'nominal');
    expect(ranked).toHaveLength(2);
    expect(ranked.length + unmeasuredCount(rows, 'nominal')).toBe(rows.length);
  });

  it('drops a row measurable in one frame but not the other', () => {
    const rows = [withReturn(0.3, null), withReturn(0.1, 0.02)];
    expect(rankByReturn(rows, 'nominal')).toHaveLength(2);
    expect(rankByReturn(rows, 'real')).toHaveLength(1);
    expect(unmeasuredCount(rows, 'real')).toBe(1);
  });

  it('returns nothing rather than a flat chart when no row is deflated', () => {
    const rows = [withReturn(0.3, null), withReturn(0.1, null)];
    expect(rankByReturn(rows, 'real')).toEqual([]);
    expect(histogramReady(rows, 'real')).toBe(false);
  });

  it('sorts best first', () => {
    const ranked = rankByReturn([withReturn(-0.2), withReturn(0.9), withReturn(0.1)], 'nominal');
    expect(ranked.map((row) => row.value)).toEqual([0.9, 0.1, -0.2]);
  });

  it('carries the fields the row needs to label itself', () => {
    const [row] = rankByReturn([withReturn(0.2)], 'nominal');
    expect(row.price).toBe(50);
    expect(row.listingDate).toBe('2026-02-10');
    expect(row.daysListed).toBe(200);
    expect(row.seasoned).toBe(true);
  });
});

describe('returnBuckets', () => {
  it('places a value exactly on an edge in the lower bucket', () => {
    // 0 counts as "did not make money". This off-by-one silently moves the
    // answer to the only question the panel asks.
    const buckets = returnBuckets([withReturn(0), withReturn(-0.5), withReturn(1)], 'nominal');
    const at = (label: string) => buckets.find((b) => b.label === label)!.count;
    expect(at('-%25 … 0')).toBe(1);
    expect(at('< -%50')).toBe(1);
    expect(at('+%50 … +%100')).toBe(1);
  });

  it('catches everything beyond the top edge', () => {
    expect(
      returnBuckets([withReturn(3)], 'nominal').find((b) => b.label === '> +%100')!.count
    ).toBe(1);
  });

  it('accounts for every measured row and no unmeasured one', () => {
    const rows = [withReturn(-3), withReturn(-0.4), withReturn(0.4), ipo({ performance: null })];
    const total = returnBuckets(rows, 'nominal').reduce((sum, b) => sum + b.count, 0);
    expect(total).toBe(3);
  });

  it('always returns every bucket, so an empty one is visible', () => {
    expect(returnBuckets([], 'nominal').map((b) => b.label)).toEqual([...BUCKET_LABELS]);
  });
});

describe('histogramReady', () => {
  it('refuses to call a handful a distribution', () => {
    const few = Array.from({ length: MIN_SAMPLE - 1 }, (_, i) =>
      withReturn(0.1 * i, null, `a${i}`)
    );
    const enough = Array.from({ length: MIN_SAMPLE }, (_, i) => withReturn(0.1 * i, null, `b${i}`));
    expect(histogramReady(few, 'nominal')).toBe(false);
    expect(histogramReady(enough, 'nominal')).toBe(true);
  });
});

describe('medianReturn and positiveShare', () => {
  it('takes the middle of an odd sample and the mean of the middle two of an even one', () => {
    expect(medianReturn([withReturn(0.1), withReturn(0.3), withReturn(0.2)], 'nominal')).toBe(0.2);
    expect(medianReturn([withReturn(0.1), withReturn(0.3)], 'nominal')).toBeCloseTo(0.2);
  });

  it('is null rather than zero on an empty sample', () => {
    expect(medianReturn([], 'nominal')).toBeNull();
    expect(positiveShare([], 'nominal')).toBeNull();
  });

  it('counts exactly zero as not positive', () => {
    expect(positiveShare([withReturn(0), withReturn(0.2)], 'nominal')).toBe(0.5);
  });
});

describe('calendarLanes', () => {
  it('groups on the month the book opens', () => {
    const rows = [
      ipo({ slug: 'a', offer_dates: { start: '2026-10-05', end: '2026-10-06', raw: null } }),
      ipo({ slug: 'b', offer_dates: { start: '2026-09-30', end: '2026-10-01', raw: null } }),
    ];
    const lanes = calendarLanes(rows);
    expect(lanes.map((lane) => lane.month)).toEqual(['2026-09', '2026-10']);
    // A book spanning a boundary appears once, in its start month.
    expect(lanes[0].entries.map((e) => e.slug)).toEqual(['b']);
    expect(lanes[1].entries.map((e) => e.slug)).toEqual(['a']);
  });

  it('excludes undated rows and undatedRows catches exactly those', () => {
    const rows = [ipo({ slug: 'a' }), ipo({ slug: 'b', offer_dates: null })];
    const placed = calendarLanes(rows).flatMap((lane) => lane.entries.map((e) => e.slug));
    const unplaced = undatedRows(rows).map((row) => row.slug);
    // Disjoint and exhaustive: no row is guessed onto a month, none is lost.
    expect(placed).toEqual(['a']);
    expect(unplaced).toEqual(['b']);
    expect([...placed, ...unplaced].sort()).toEqual(['a', 'b']);
  });

  it('orders entries inside a month by start date', () => {
    const rows = [
      ipo({ slug: 'late', offer_dates: { start: '2026-10-20', end: '2026-10-21', raw: null } }),
      ipo({ slug: 'early', offer_dates: { start: '2026-10-02', end: '2026-10-03', raw: null } }),
    ];
    expect(calendarLanes(rows)[0].entries.map((e) => e.slug)).toEqual(['early', 'late']);
  });
});

describe('allocationSegments', () => {
  const results = (share: number[]): IpoResults => ({
    groups: [
      {
        key: 'domestic_retail',
        label: 'Yurt İçi Bireysel',
        investors: 1,
        lots: 1,
        share: share[0],
      },
      {
        key: 'domestic_institutional',
        label: 'Yurt İçi Kurumsal',
        investors: 1,
        lots: 1,
        share: share[1],
      },
    ],
    total_investors: 2,
    total_lots: 2,
  });

  it('is null when there is nothing published, so the caller renders the absence', () => {
    expect(allocationSegments(null)).toBeNull();
    expect(allocationSegments({ groups: [], total_investors: null, total_lots: null })).toBeNull();
  });

  it('passes an under-100 total through so the bar leaves bare track', () => {
    // The source rounds; stretching to 100% would invent precision the filing
    // never claimed.
    const built = allocationSegments(results([0.9, 0.08]))!;
    expect(built.total).toBeCloseTo(0.98);
    expect(built.segments).toHaveLength(2);
  });

  it('gives an unrecognised group a colour rather than dropping it', () => {
    const built = allocationSegments({
      groups: [{ key: 'other', label: 'Başka', investors: null, lots: 1, share: 1 }],
      total_investors: null,
      total_lots: 1,
    })!;
    expect(built.segments[0].label).toBe('Başka');
    expect(built.segments[0].color).toBeTruthy();
  });
});

describe('structureSegments', () => {
  const structure = (increase: number | null, sale: number | null): IpoStructure => ({
    capital_increase_lots: increase,
    share_sale_lots: sale,
    capital_increase_share: null,
    spk_bulletin: '2026/52',
  });

  it('splits new capital from shareholder sale', () => {
    const built = structureSegments(structure(30_000_000, 10_000_000))!;
    expect(built.segments.map((s) => s.key)).toEqual(['capital_increase', 'share_sale']);
    expect(built.segments[0].weight).toBeCloseTo(0.75);
  });

  it('yields one full-width segment when a side is zero', () => {
    // A zero-width second segment renders as a hairline a reader could misread
    // as a sliver of the other kind.
    const built = structureSegments(structure(40_000_000, 0))!;
    expect(built.segments).toHaveLength(1);
    expect(built.segments[0].weight).toBe(1);
  });

  it('is null when nothing was published', () => {
    expect(structureSegments(null)).toBeNull();
    expect(structureSegments(structure(null, null))).toBeNull();
    expect(structureSegments(structure(0, 0))).toBeNull();
  });
});

describe('proceedsSegments', () => {
  it('keeps the prospectus order rather than sorting by size', () => {
    // The order is the company's own stated priority.
    const built = proceedsSegments([
      { label: 'İşletme sermayesi', share: 0.35 },
      { label: 'Yatırımların finansmanı', share: 0.65 },
    ])!;
    expect(built.segments.map((s) => s.label)).toEqual([
      'İşletme sermayesi',
      'Yatırımların finansmanı',
    ]);
  });

  it('is null when absent', () => {
    expect(proceedsSegments(null)).toBeNull();
    expect(proceedsSegments([])).toBeNull();
    expect(proceedsSegments([{ label: 'x', share: null }])).toBeNull();
  });
});

describe('absentCopy', () => {
  it('gives four different situations four different sentences', () => {
    const notListed = ipo({ state: 'upcoming', performance: null });
    const noCode = ipo({ state: 'upcoming', ticker: null, performance: null });
    const band = ipo({
      state: 'listed',
      performance: null,
      price: { low: 12, high: 14.5, is_band: true, raw: '12,00 - 14,50 TL' },
    });
    const unreadable = ipo({ state: 'listed', performance: null, unparsed: ['detail'] });

    const texts = [
      absentCopy(notListed, 'performance'),
      absentCopy(noCode, 'performance'),
      absentCopy(band, 'performance'),
      absentCopy(unreadable, 'performance'),
    ];
    expect(new Set(texts).size).toBe(4);
  });

  it('explains why a band yields no return', () => {
    const band = ipo({
      state: 'listed',
      performance: null,
      price: { low: 12, high: 14.5, is_band: true, raw: '12,00 - 14,50 TL' },
    });
    expect(absentCopy(band, 'performance')).toContain('ortası');
  });

  it('tells a published-later results block apart from an unfinished book', () => {
    expect(absentCopy(ipo({ state: 'listed' }), 'results')).not.toBe(
      absentCopy(ipo({ state: 'upcoming' }), 'results')
    );
  });

  it('has copy for every block', () => {
    for (const block of ['results', 'structure', 'proceeds', 'performance'] as const) {
      expect(absentCopy(ipo(), block).length).toBeGreaterThan(10);
    }
  });
});

describe('ipoStateLabel', () => {
  it('names every state in Turkish', () => {
    const states: IpoState[] = ['undated', 'upcoming', 'book_open', 'listed'];
    const labels = states.map(ipoStateLabel);
    expect(new Set(labels).size).toBe(4);
    expect(labels.every((label) => label.length > 0)).toBe(true);
  });
});
