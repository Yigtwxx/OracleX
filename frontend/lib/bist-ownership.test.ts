/**
 * The rules the Ortaklık board and the company-page panel agree on.
 *
 * What is pinned is where "no answer" and "zero" part ways: a holder table
 * with no rows is a company nobody crosses 5% of, not one nobody owns; the
 * pooled tail is never coloured as a holding; and the coverage line is
 * derived from the rows beside it so the two cannot disagree.
 */

import { describe, expect, it } from 'vitest';

import type { BistOwnershipEntity, BistOwnershipFacts, BistOwnershipHolder } from './bist-api';
import {
  CATEGORY_ORDER,
  allocationSegments,
  allocationSummary,
  boardSummary,
  filterByCategory,
  holderCoverage,
  formatStakeDelta,
  holderHeadline,
  isHolderCategory,
  ownershipChips,
  sinceLabel,
  tickerColor,
} from './bist-ownership';

function entity(overrides: Partial<BistOwnershipEntity> = {}): BistOwnershipEntity {
  return {
    id: 'tvf',
    name: 'Türkiye Varlık Fonu',
    subtitle: null,
    category: 'state',
    total_value_try: 1e12,
    positions_count: 3,
    allocation: [],
    top_positions: [],
    last_move: null,
    as_of: null,
    stale: false,
    issues: [],
    has_data: true,
    coverage_note: null,
    ...overrides,
  };
}

function holder(label: string, stake: number, tracked: boolean): BistOwnershipHolder {
  return {
    label,
    stake_pct: stake,
    value_try: null,
    entity_id: tracked ? 'x' : null,
    tracked,
    since: null,
    at_baseline: true,
    previous_stake_pct: null,
    delta_pct: null,
  };
}

describe('category filter', () => {
  it('lists every category exactly once in display order', () => {
    expect(new Set(CATEGORY_ORDER).size).toBe(CATEGORY_ORDER.length);
    expect(CATEGORY_ORDER[0]).toBe('state');
  });

  it('accepts only known categories from the URL', () => {
    expect(isHolderCategory('fund')).toBe(true);
    expect(isHolderCategory('politician')).toBe(false);
    expect(isHolderCategory(null)).toBe(false);
  });

  it('null means everything', () => {
    const rows = [entity(), entity({ id: 'koc', category: 'holding' })];
    expect(filterByCategory(rows, null)).toHaveLength(2);
    expect(filterByCategory(rows, 'holding').map((e) => e.id)).toEqual(['koc']);
  });
});

describe('allocation segments', () => {
  it('colours named slices and mutes the pooled tail', () => {
    const segments = allocationSegments([
      { key: 'THYAO', label: 'THY', ticker: 'THYAO', value_try: 60, pct: 0.6 },
      { key: '__other__', label: 'Diğer 4 pozisyon', ticker: null, value_try: 40, pct: 0.4 },
    ]);

    expect(segments[0].pooled).toBe(false);
    expect(segments[1].pooled).toBe(true);
    expect(segments[1].color).toBe('var(--fg-subtle)');
    expect(segments[0].color).not.toBe(segments[1].color);
  });

  it('gives one ticker the same colour on every card', () => {
    const a = allocationSegments([
      { key: 'THYAO', label: 'THY', ticker: 'THYAO', value_try: 1, pct: 1 },
    ]);
    const b = allocationSegments([
      { key: 'HALKB', label: 'Halkbank', ticker: 'HALKB', value_try: 2, pct: 0.7 },
      { key: 'THYAO', label: 'THY', ticker: 'THYAO', value_try: 1, pct: 0.3 },
    ]);
    expect(a[0].color).toBe(b[1].color);
    expect(b[0].color).not.toBe(b[1].color);
    expect(tickerColor('THYAO')).toMatch(/^hsl\(\d+ 68% (54|62|70)%\)$/);
    expect(tickerColor('THYAO')).toBe(tickerColor('THYAO'));
  });

  it('drops empty slices rather than drawing a zero-width one', () => {
    expect(
      allocationSegments([{ key: 'X', label: 'X', ticker: 'X', value_try: 0, pct: 0 }])
    ).toEqual([]);
  });

  it('summarises for a screen reader, with one decimal only under ten percent', () => {
    const summary = allocationSummary(
      allocationSegments([
        { key: 'A', label: 'A', ticker: 'A', value_try: 91, pct: 0.914 },
        { key: 'B', label: 'B', ticker: 'B', value_try: 8.6, pct: 0.086 },
      ])
    );
    expect(summary).toBe('A %91, B %8,6');
    expect(allocationSummary([])).toBe('Değerlenebilen pozisyon yok');
  });
});

describe('holder coverage', () => {
  it('derives the remainder from the rows rather than reading it', () => {
    const coverage = holderCoverage({
      holders: [holder('TVF', 0.4912, true), holder('X', 0.06, false)],
    });
    expect(coverage.namedPct).toBeCloseTo(0.5512);
    expect(coverage.otherPct).toBeCloseTo(0.4488);
    expect(coverage.tracked).toBe(1);
    expect(coverage.untracked).toBe(1);
  });

  it('never reports a negative remainder when stakes overshoot by rounding', () => {
    expect(
      holderCoverage({ holders: [holder('A', 0.6, true), holder('B', 0.405, false)] }).otherPct
    ).toBe(0);
  });
});

describe('holder headline', () => {
  it('says out loud that nobody crosses the threshold', () => {
    expect(holderHeadline({ holders: [] })).toMatch(/%5 eşiğini geçen ortak yok/);
  });

  it('names a majority holder', () => {
    expect(holderHeadline({ holders: [holder('Türkiye Varlık Fonu', 0.9149, true)] })).toBe(
      'Türkiye Varlık Fonu %91,5 ile çoğunluk ortağı.'
    );
  });

  it('describes a split capital by count and share', () => {
    const line = holderHeadline({
      holders: [holder('Koç Holding', 0.3932, true), holder('Ford', 0.4104, true)],
    });
    expect(line).toMatch(/^2 ortak sermayenin %80,4'ini tutuyor/);
    expect(line).toMatch(/en büyüğü Koç Holding \(%39,3\)/);
  });
});

describe('board summary', () => {
  it('sums only what was valued and counts only what has data', () => {
    const summary = boardSummary({
      entities: [
        entity(),
        entity({ id: 'koc', total_value_try: 5e11 }),
        entity({ id: 'empty', has_data: false, total_value_try: null }),
      ],
      tickers_covered: 98,
      tickers_total: 100,
      universe: 'XU100',
    });
    expect(summary.entities).toBe(3);
    expect(summary.withData).toBe(2);
    expect(summary.totalValued).toBe(1.5e12);
    expect(summary.coverage).toBe('98/100 XU100');
  });

  it('reports null, not zero, when nothing could be valued', () => {
    const summary = boardSummary({
      entities: [entity({ has_data: false, total_value_try: null })],
      tickers_covered: 0,
      tickers_total: 100,
      universe: 'XU100',
    });
    expect(summary.totalValued).toBeNull();
  });
});

describe('stake history', () => {
  it('never prints the baseline day as an entry date', () => {
    expect(sinceLabel(null, true)).toBe('Kayıt yok');
    expect(sinceLabel('2026-09-02', true)).toBe('≤ 2 Eyl 2026');
    expect(sinceLabel('2026-09-05', false)).toBe('Giriş 5 Eyl 2026');
  });

  it('keeps unknown and unchanged apart', () => {
    expect(formatStakeDelta(null)).toBe('—');
    expect(formatStakeDelta(0)).toBe('0');
    expect(formatStakeDelta(0.0412)).toBe('+4.1 puan');
    expect(formatStakeDelta(-0.0045)).toBe('-0.45 puan');
  });
});

describe('ownership note chips', () => {
  const facts: BistOwnershipFacts = {
    stance: 'family_holdings',
    coverage: {
      universe: 'XU100',
      tickers_covered: 100,
      tickers_total: 100,
      entities: 87,
      entities_with_data: 80,
      as_of: '2026-09-02',
      tracking_since: '2026-09-02',
      tracking_days: 1,
    },
    total: {
      valued_try_bn: 7520,
      categories: [
        { category: 'holding', share_pct: 49, entities: 50 },
        { category: 'state', share_pct: 34, entities: 5 },
      ],
    },
    holders: { top: [], top3_share_pct: 37 },
    companies: {
      with_named_holder: 99,
      without_named_holder: 1,
      majority_held: 37,
      median_named_stake_pct: 62,
      median_free_float_pct: 36,
      median_foreign_ratio_pct: null,
      foreign_high: [],
      foreign_low: [],
    },
    moves: {
      stake_total: 0,
      stake_kinds: {},
      recent_stakes: [],
      filing_kinds: {},
      recent_filings: [],
    },
    funds: { tracked: 10, readable: 3 },
    not_measured: [],
    stale: false,
  };

  it('renders the split, concentration and majority count, and skips unknown readings', () => {
    const texts = ownershipChips(facts).map((c) => c.text);
    expect(texts[0]).toBe('holding %49 · kamu %34');
    expect(texts).toContain('ilk 3 ortak %37');
    expect(texts).toContain('medyan sahiplik %62');
    expect(texts).toContain('37 şirkette çoğunluk ortağı');
    expect(texts.some((t) => t.startsWith('yabancı'))).toBe(false);
  });
});
