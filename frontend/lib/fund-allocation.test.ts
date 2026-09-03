/**
 * The fund allocation bar's ordering and colour rules.
 *
 * Lives under `lib/` with the other pure-function tests even though the bar it
 * serves sits in `components/` — same reason as `ownership-allocation-colors`:
 * it is plain data in, plain data out, and the rendered bar is verified in a
 * real browser instead.
 *
 * What is worth pinning here is the pair of invariants the column depends on
 * and neither of which is visible from a single bar: the order is fixed, and
 * so is the colour. Both exist so two rows of the screener can be read against
 * each other, and both would break silently.
 */

import { describe, expect, it } from 'vitest';

import {
  FUND_BUCKET_COLOR,
  FUND_BUCKET_ORDER,
  allocationSegments,
  allocationSummary,
  allocationTotal,
  bucketColor,
  dominantBucket,
  equityWeight,
  formatWeight,
} from '@/lib/fund-allocation';

const LABELS: Record<string, string> = {
  hisse: 'Hisse senedi',
  yabanci_hisse: 'Yabancı hisse senedi',
  mevduat: 'Mevduat ve katılma hesabı',
  fon: 'Fon katılma payları',
  diger: 'Diğer',
};

describe('the palette', () => {
  it('gives every bucket a colour', () => {
    for (const key of FUND_BUCKET_ORDER) {
      expect(FUND_BUCKET_COLOR[key], `no colour for ${key}`).toBeTruthy();
    }
  });

  it('never gives two buckets the same colour', () => {
    const fills = FUND_BUCKET_ORDER.map((key) => FUND_BUCKET_COLOR[key]);
    expect(new Set(fills).size).toBe(fills.length);
  });

  it('falls back to the "Diğer" colour for a bucket it has not heard of', () => {
    expect(bucketColor('a_bucket_added_later')).toBe(FUND_BUCKET_COLOR.diger);
  });
});

describe('allocationSegments', () => {
  it('returns nothing when TEFAS published nothing', () => {
    expect(allocationSegments(null)).toEqual([]);
    expect(allocationSegments(undefined)).toEqual([]);
  });

  it('orders by the bar order, not by the response order', () => {
    const forwards = allocationSegments({ hisse: 0.6, mevduat: 0.4 }, LABELS);
    const backwards = allocationSegments({ mevduat: 0.4, hisse: 0.6 }, LABELS);
    expect(forwards.map((s) => s.key)).toEqual(['hisse', 'mevduat']);
    expect(backwards.map((s) => s.key)).toEqual(['hisse', 'mevduat']);
  });

  it('orders by the bar order, not by weight', () => {
    // The largest slice does not come first: a fixed position per asset class
    // is what lets a reader compare two rows without reading the legend twice.
    const segments = allocationSegments({ hisse: 0.1, mevduat: 0.9 }, LABELS);
    expect(segments.map((s) => s.key)).toEqual(['hisse', 'mevduat']);
  });

  it('drops zero and negative weights', () => {
    const segments = allocationSegments({ hisse: 0.6, mevduat: 0, fon: -0.1 }, LABELS);
    expect(segments.map((s) => s.key)).toEqual(['hisse']);
  });

  it('keeps a bucket it has not heard of, with the label the server sent', () => {
    const segments = allocationSegments(
      { hisse: 0.6, kripto: 0.4 },
      { ...LABELS, kripto: 'Kripto varlıklar' }
    );
    expect(segments.map((s) => s.key)).toEqual(['hisse', 'kripto']);
    expect(segments[1].label).toBe('Kripto varlıklar');
    expect(segments[1].color).toBe(FUND_BUCKET_COLOR.diger);
  });

  it('falls back to the key when no label was sent', () => {
    expect(allocationSegments({ hisse: 1 })[0].label).toBe('hisse');
  });
});

describe('allocationTotal', () => {
  it('reports what TEFAS reported and never clamps it to one', () => {
    expect(allocationTotal({ hisse: 0.5, mevduat: 0.497 })).toBeCloseTo(0.997);
  });

  it('is zero when nothing was published', () => {
    expect(allocationTotal(null)).toBe(0);
  });
});

describe('equityWeight', () => {
  it('sums domestic and foreign equity', () => {
    expect(equityWeight({ hisse: 0.5, yabanci_hisse: 0.2, mevduat: 0.3 })).toBeCloseTo(0.7);
  });

  it('is null when nothing was published, so the row sorts last', () => {
    expect(equityWeight(null)).toBeNull();
  });

  it('is zero — not null — for a fund that reported and holds no equity', () => {
    // "TEFAS says this fund holds no stocks" and "TEFAS says nothing" are
    // different claims, and the sort has to keep them apart.
    expect(equityWeight({ mevduat: 1 })).toBe(0);
  });
});

describe('dominantBucket', () => {
  it('picks the largest', () => {
    const segments = allocationSegments({ hisse: 0.3, mevduat: 0.7 }, LABELS);
    expect(dominantBucket(segments)?.key).toBe('mevduat');
  });

  it('breaks a tie on bar order, so two identical funds agree', () => {
    const segments = allocationSegments({ hisse: 0.5, mevduat: 0.5 }, LABELS);
    expect(dominantBucket(segments)?.key).toBe('hisse');
  });

  it('is null with nothing to pick from', () => {
    expect(dominantBucket([])).toBeNull();
  });
});

describe('formatWeight', () => {
  it('never prints a real holding as zero', () => {
    // The bar keeps a 0.03% line at 2px so it cannot vanish; printing "%0,0"
    // beside it would make the same claim the width refuses to make.
    expect(formatWeight(0.0003)).toBe('<%0,1');
  });

  it('leaves an ordinary weight alone', () => {
    expect(formatWeight(0.532)).toBe('%53,2');
  });

  it('prints a genuine zero as zero', () => {
    expect(formatWeight(0)).toBe('%0,0');
  });
});

describe('allocationSummary', () => {
  it('reads as one Turkish sentence in bar order', () => {
    const segments = allocationSegments({ hisse: 0.532, mevduat: 0.145 }, LABELS);
    expect(allocationSummary(segments)).toBe(
      'Hisse senedi %53,2 · Mevduat ve katılma hesabı %14,5'
    );
  });

  it('is empty when there is nothing to say', () => {
    expect(allocationSummary([])).toBe('');
  });
});
