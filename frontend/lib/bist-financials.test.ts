import { describe, expect, it } from 'vitest';

import type { BistFinancials, BistQuarter } from '@/lib/bist-api';
import {
  absentCopy,
  basisAvailable,
  basisNotice,
  chartState,
  effectiveBasis,
  fieldState,
  indexedComparison,
  marginSeries,
  metricTiles,
  quarterSeries,
  seasonalGrid,
  unitFor,
} from '@/lib/bist-financials';

const INDUSTRIAL_FIELDS = [
  'revenue',
  'gross_profit',
  'operating_profit',
  'ebitda',
  'net_income',
  'financing_expense',
  'ocf',
  'capex',
  'fcf',
  'dividends_paid',
  'equity',
  'total_assets',
  'total_debt',
  'short_term_debt',
  'cash',
  'current_assets',
  'current_liabilities',
];
const BANK_FIELDS = ['revenue', 'operating_profit', 'net_income', 'equity', 'total_assets'];
const INSURANCE_FIELDS = ['net_income', 'equity', 'total_assets'];

function quarter(
  period: string,
  year: number,
  q: number,
  revenue: number,
  { deflator = 1, real = true }: { deflator?: number; real?: boolean } = {}
): BistQuarter {
  const nominal = {
    revenue,
    gross_profit: revenue * 0.3,
    operating_profit: revenue * 0.2,
    ebitda: revenue * 0.25,
    net_income: revenue * 0.1,
    equity: revenue * 5,
    total_assets: revenue * 20,
    total_debt: revenue * 3,
    short_term_debt: revenue * 1.2,
    cash: revenue * 0.8,
    ocf: revenue * 0.12,
    current_assets: revenue * 4,
    current_liabilities: revenue * 3.5,
    financing_expense: -revenue * 0.04,
    capex: -revenue * 0.06,
    fcf: revenue * 0.06,
    dividends_paid: -revenue * 0.02,
  };
  return {
    period,
    year,
    quarter: q,
    nominal,
    real: real
      ? Object.fromEntries(Object.entries(nominal).map(([k, v]) => [k, v * deflator]))
      : null,
    deflator: real ? deflator : null,
    provisional: false,
  };
}

function board(overrides: Partial<BistFinancials> = {}): BistFinancials {
  const quarters = [
    quarter('2025Q1', 2025, 1, 100, { deflator: 1.3 }),
    quarter('2025Q2', 2025, 2, 120, { deflator: 1.2 }),
    quarter('2025Q3', 2025, 3, 140, { deflator: 1.1 }),
    quarter('2025Q4', 2025, 4, 160, { deflator: 1.0 }),
  ];
  return {
    ticker: 'TEST',
    name: 'Test A.Ş.',
    sector: 'Sanayi',
    layout: 'industrial',
    layout_label: 'Sanayi/ticaret şablonu',
    layout_fields: INDUSTRIAL_FIELDS,
    available_fields: INDUSTRIAL_FIELDS,
    latest_period: '2025Q4',
    fetched_at: '2026-01-02T00:00:00Z',
    source_url: 'https://example.invalid',
    quarters,
    ratios: quarters.map((q) => ({
      period: q.period,
      gross_margin: 0.3,
      operating_margin: 0.2,
      ebitda_margin: 0.25,
      net_margin: 0.1,
      current_ratio: 1.14,
      short_debt_share: 0.4,
      cash_conversion: 1.2,
      net_debt_ebitda: 2.2,
      roe_ttm: 0.18,
    })),
    ttm: {
      revenue: 520,
      ebitda: 130,
      net_income: 52,
      real_revenue_growth: -0.08,
      real_ebitda_growth: -0.1,
      real_net_income_growth: -0.05,
      real_equity_growth: 0.02,
      nominal_revenue_growth: 0.35,
      margin_trend: -0.01,
      inflation_yoy: 0.42,
      loss_quarters: 0,
    },
    deflation: {
      available: true,
      reason: null,
      base_period: '2025Q4',
      base_month: '2025-12',
      cpi_latest_month: '2025-12',
      cpi_series: 'TP.FG.J0',
      provisional_periods: [],
      uncovered_periods: [],
    },
    market: null,
    stale: false,
    ...overrides,
  };
}

const OFF = {
  available: false,
  reason: 'cpi_key_missing' as const,
  base_period: null,
  base_month: null,
  cpi_latest_month: null,
  cpi_series: 'TP.FG.J0',
  provisional_periods: [],
  uncovered_periods: [],
};

describe('effectiveBasis', () => {
  it('honours the request when the board was deflated', () => {
    expect(effectiveBasis('real', board().deflation)).toBe('real');
    expect(effectiveBasis('nominal', board().deflation)).toBe('nominal');
  });

  it('never returns real when nothing was deflated', () => {
    // The regression this pins is the one the board exists to prevent:
    // returning 'real' here paints nominal lira under a "Reel" label.
    expect(effectiveBasis('real', OFF)).toBe('nominal');
    expect(effectiveBasis('real', null)).toBe('nominal');
    expect(effectiveBasis('real', undefined)).toBe('nominal');
  });

  it('reports availability to the toggle so it can disable rather than silently switch', () => {
    expect(basisAvailable(board().deflation)).toBe(true);
    expect(basisAvailable(OFF)).toBe(false);
  });
});

describe('basisNotice', () => {
  it('gives each unavailability reason its own sentence', () => {
    const reasons = ['cpi_key_missing', 'cpi_unavailable', 'cpi_too_short'] as const;
    const texts = reasons.map((reason) => basisNotice({ ...OFF, reason })!.text);
    expect(new Set(texts).size).toBe(3);
    for (const text of texts) {
      expect(text).toContain('nominal');
    }
  });

  it('warns rather than murmurs when the frame is off', () => {
    expect(basisNotice(OFF)!.tone).toBe('warn');
  });

  it('says nothing when every quarter was cleanly deflated', () => {
    expect(basisNotice(board().deflation)).toBeNull();
  });

  it('names provisional and uncovered quarters without raising the tone', () => {
    const notice = basisNotice({
      ...board().deflation,
      provisional_periods: ['2025Q4'],
      uncovered_periods: ['2023Q1'],
    })!;
    expect(notice.tone).toBe('muted');
    expect(notice.text).toContain('2025Q4');
    expect(notice.text).toContain('2023Q1');
  });
});

describe('fieldState', () => {
  it('tells a missing chart-of-accounts line apart from an unreported one', () => {
    const bank = board({
      layout: 'bank',
      layout_fields: BANK_FIELDS,
      available_fields: BANK_FIELDS,
    });
    expect(fieldState(bank, 'ebitda')).toBe('absent_layout');

    const shy = board({ available_fields: INDUSTRIAL_FIELDS.filter((f) => f !== 'ebitda') });
    expect(fieldState(shy, 'ebitda')).toBe('absent_unreported');

    expect(fieldState(board(), 'ebitda')).toBe('present');
  });

  it('gives the two absences different copy', () => {
    const bank = board({
      layout: 'bank',
      layout_fields: BANK_FIELDS,
      available_fields: BANK_FIELDS,
    });
    const shy = board({ available_fields: INDUSTRIAL_FIELDS.filter((f) => f !== 'ebitda') });
    const layoutCopy = absentCopy(bank, ['ebitda']);
    const unreportedCopy = absentCopy(shy, ['ebitda']);
    expect(layoutCopy).not.toBe(unreportedCopy);
    expect(layoutCopy).toContain('şablonunda yok');
    expect(unreportedCopy).toContain('bildirmemiş');
  });
});

describe('chartState', () => {
  it('is the weakest of the fields a chart needs', () => {
    const bank = board({
      layout: 'bank',
      layout_fields: BANK_FIELDS,
      available_fields: BANK_FIELDS,
    });
    expect(chartState(bank, ['ocf', 'net_income'])).toBe('absent_layout');
    expect(chartState(board(), ['ocf', 'net_income'])).toBe('present');
  });

  it('prefers the layout reason when both kinds of absence are present', () => {
    const mixed = board({
      layout: 'bank',
      layout_fields: BANK_FIELDS,
      available_fields: BANK_FIELDS.filter((f) => f !== 'operating_profit'),
    });
    expect(chartState(mixed, ['ebitda', 'operating_profit'])).toBe('absent_layout');
  });
});

describe('insurance layout', () => {
  const insurer = board({
    layout: 'insurance',
    layout_fields: INSURANCE_FIELDS,
    available_fields: INSURANCE_FIELDS,
  });

  it('still yields a board rather than an empty page', () => {
    // The assertion that proves the degradation is real: an insurer's page has
    // to look deliberate, not broken.
    expect(chartState(insurer, ['equity', 'total_assets'])).toBe('present');
    expect(metricTiles(insurer, 'real').length).toBeGreaterThanOrEqual(3);
  });

  it('drops the tiles it cannot measure instead of showing zeroes', () => {
    const labels = metricTiles(insurer, 'real').map((t) => t.label);
    expect(labels).not.toContain('Son çeyrek hasılat');
    expect(labels).not.toContain('FAVÖK marjı');
    expect(labels).toContain('Özkaynak kârlılığı');
  });
});

describe('quarterSeries', () => {
  it('omits an undeflated quarter rather than plotting it at zero', () => {
    // Zero on a revenue chart is a company that sold nothing, which is a claim.
    const partial = board();
    partial.quarters[0] = { ...partial.quarters[0], real: null, deflator: null };
    const [series] = quarterSeries(partial, 'real', ['revenue']);
    expect(series.points).toHaveLength(3);
    expect(series.points.map((p) => p.period)).toEqual(['2025Q2', '2025Q3', '2025Q4']);
  });

  it('keeps every quarter in the nominal frame', () => {
    const partial = board();
    partial.quarters[0] = { ...partial.quarters[0], real: null, deflator: null };
    expect(quarterSeries(partial, 'nominal', ['revenue'])[0].points).toHaveLength(4);
  });

  it('carries a null value through without dropping the quarter', () => {
    const gap = board();
    gap.quarters[1] = {
      ...gap.quarters[1],
      nominal: { ...gap.quarters[1].nominal, revenue: null },
    };
    const [series] = quarterSeries(gap, 'nominal', ['revenue']);
    expect(series.points).toHaveLength(4);
    expect(series.points[1].value).toBeNull();
  });
});

describe('marginSeries', () => {
  it('is the same in either frame because inflation cancels out of a ratio', () => {
    expect(marginSeries(board())).toHaveLength(3);
  });

  it('drops a margin no quarter could measure', () => {
    const bank = board({
      layout: 'bank',
      layout_fields: BANK_FIELDS,
      available_fields: BANK_FIELDS,
    });
    bank.ratios = bank.ratios.map((row) => ({ ...row, gross_margin: null }));
    expect(marginSeries(bank).map((s) => s.field)).not.toContain('gross_margin');
  });
});

describe('indexedComparison', () => {
  it('pins both series to 100 at the same quarter', () => {
    const { rows, basePeriod, rebased } = indexedComparison(board(), 'revenue');
    expect(basePeriod).toBe('2025Q1');
    expect(rebased).toBe(false);
    expect(rows[0].nominal).toBeCloseTo(100);
    expect(rows[0].real).toBeCloseTo(100);
  });

  it('shows the gap the board exists to show', () => {
    // Nominal revenue rose 60%; deflated, it barely moved.
    const { rows } = indexedComparison(board(), 'revenue');
    const last = rows[rows.length - 1];
    expect(last.nominal).toBeGreaterThan(last.real!);
  });

  it('rebases onto the oldest covered quarter and says that it did', () => {
    const partial = board();
    partial.quarters[0] = { ...partial.quarters[0], real: null, deflator: null };
    const { basePeriod, rebased, rows } = indexedComparison(partial, 'revenue');
    expect(basePeriod).toBe('2025Q2');
    expect(rebased).toBe(true);
    expect(rows[0].nominal).toBeCloseTo(100);
  });

  it('returns nothing rather than a broken axis when no quarter is usable', () => {
    const none = board({ deflation: OFF });
    none.quarters = none.quarters.map((q) => ({ ...q, real: null, deflator: null }));
    expect(indexedComparison(none, 'revenue').rows).toHaveLength(0);
  });
});

describe('seasonalGrid', () => {
  it('places a quarter in its own column', () => {
    const rows = seasonalGrid(board(), 'nominal', 'revenue');
    expect(rows).toHaveLength(1);
    expect(rows[0].year).toBe(2025);
    expect(rows[0].cells[2]).toBe(140);
  });

  it('keeps four cells for a year that reported two quarters', () => {
    // A shortened row would slide Q3 under the Q1 column.
    const partial = board();
    partial.quarters = [partial.quarters[0], partial.quarters[2]];
    const rows = seasonalGrid(partial, 'nominal', 'revenue');
    expect(rows[0].cells).toHaveLength(4);
    expect(rows[0].cells[1]).toBeNull();
    expect(rows[0].cells[3]).toBeNull();
  });

  it('orders years oldest first', () => {
    const two = board();
    two.quarters = [quarter('2024Q4', 2024, 4, 80), ...two.quarters];
    expect(seasonalGrid(two, 'nominal', 'revenue').map((r) => r.year)).toEqual([2024, 2025]);
  });
});

describe('unitFor', () => {
  it('picks one divisor for every series in a chart', () => {
    // A per-series divisor makes a stacked bar lie: equal heights, unequal
    // magnitudes.
    expect(unitFor([4.2e9, 1.1e6, null]).divisor).toBe(1e9);
    expect(unitFor([4.2e9, 1.1e6]).label).toBe('milyar TL');
    expect(unitFor([3.5e6, 900]).divisor).toBe(1e6);
    expect(unitFor([120, null, undefined]).divisor).toBe(1);
  });

  it('scales on magnitude, so a large negative counts', () => {
    expect(unitFor([-4.2e9, 10]).divisor).toBe(1e9);
  });

  it('survives an all-empty chart', () => {
    expect(unitFor([null, undefined]).divisor).toBe(1);
  });
});

describe('metricTiles', () => {
  it('renders an unmeasurable figure as a dash rather than a zero', () => {
    const blank = board();
    blank.ratios = blank.ratios.map((row) => ({ ...row, roe_ttm: null, net_debt_ebitda: null }));
    const tiles = metricTiles(blank, 'real');
    const roe = tiles.find((t) => t.label === 'Özkaynak kârlılığı')!;
    expect(roe.value).toBe('—');
  });

  it('distinguishes an unmeasurable loss count from zero losses', () => {
    const unknown = board({ ttm: { ...board().ttm, loss_quarters: null } });
    expect(metricTiles(unknown, 'real').find((t) => t.label === 'Zarar eden çeyrek')!.value).toBe(
      '—'
    );
    expect(metricTiles(board(), 'real').find((t) => t.label === 'Zarar eden çeyrek')!.value).toBe(
      '0 / 4'
    );
  });

  it('renames the growth tile instead of showing a dash under a Reel heading', () => {
    // A card headed with a frame it could not compute reads as a figure that
    // failed to load, when the truth is that the frame is unavailable.
    const off = board({ deflation: OFF });
    const labels = metricTiles(off, 'nominal').map((t) => t.label);
    expect(labels).toContain('Nominal hasılat büyümesi');
    expect(labels).not.toContain('Reel hasılat büyümesi');

    const tile = metricTiles(off, 'nominal').find((t) => t.label === 'Nominal hasılat büyümesi')!;
    expect(tile.value).not.toBe('—');
  });

  it('names the frame the quarterly figure is quoted in', () => {
    expect(metricTiles(board(), 'real')[0].note).toContain('reel');
    expect(metricTiles(board(), 'nominal')[0].note).toContain('nominal');
  });
});
