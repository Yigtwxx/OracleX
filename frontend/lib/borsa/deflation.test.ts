import { describe, expect, it } from 'vitest';

import type { BistFund } from '@/lib/bist-api';
import { buildDeflation, positionOf } from './deflation';

function fund(code: string, nominal: number, real: number | null): BistFund {
  return {
    code,
    title: `${code} portföy fonu`,
    umbrella: 'Hisse Senedi Şemsiye Fonu',
    tradable: true,
    risk_value: 5,
    returns: { '1y': nominal },
    framed_returns: { '1y': { nominal, real, usd: null } },
    allocation: null,
  };
}

describe('buildDeflation', () => {
  it('drops funds with no deflator rather than plotting them at zero erosion', () => {
    const scale = buildDeflation([fund('AAA', 0.5, 0.1), fund('BBB', 0.4, null)], '1y');
    expect(scale.rows.map((row) => row.code)).toEqual(['AAA']);
  });

  it('ranks by the nominal figure the reader arrived with', () => {
    const scale = buildDeflation([fund('LOW', 0.2, 0.1), fund('HIGH', 2, 0.5)], '1y');
    expect(scale.rows.map((row) => row.code)).toEqual(['HIGH', 'LOW']);
  });

  it('counts a nominal gain that ended negative as a real loss', () => {
    const scale = buildDeflation([fund('AAA', 0.315, -0.002), fund('BBB', 2, 0.5)], '1y');
    expect(scale.realLosses).toBe(1);
    expect(scale.rows.find((row) => row.code === 'AAA')?.realLoss).toBe(true);
    expect(scale.rows.find((row) => row.code === 'BBB')?.realLoss).toBe(false);
  });

  it('reports what the limit dropped instead of truncating silently', () => {
    const funds = Array.from({ length: 5 }, (_, i) => fund(`F${i}`, 1 - i / 10, 0.1));
    const scale = buildDeflation(funds, '1y', 3);
    expect(scale.rows).toHaveLength(3);
    expect(scale.omitted).toBe(2);
  });

  it('cuts the axis at the bulk and reports the rows that run past it', () => {
    // One extreme fund and nine ordinary ones: the outlier must not set the
    // domain, or every other row collapses into the left of the track.
    const funds = [
      fund('OUT', 13, 9.6),
      ...Array.from({ length: 9 }, (_, i) => fund(`F${i}`, 1 - i / 20, 0.5 - i / 20)),
    ];
    const scale = buildDeflation(funds, '1y');
    expect(scale.offScale).toBe(1);
    expect(scale.rows.find((row) => row.code === 'OUT')?.offScale).toBe(true);
    expect(scale.rows.find((row) => row.code === 'F5')?.offScale).toBe(false);
    // The ordinary rows now use the width they were being denied.
    expect(positionOf(scale, 1 - 8 / 20)).toBeGreaterThan(0.5);
  });

  it('keeps zero inside the domain even when every row is a gain', () => {
    const scale = buildDeflation([fund('AAA', 0.5, 0.3)], '1y');
    expect(scale.min).toBeLessThanOrEqual(0);
    expect(scale.zero).toBeGreaterThanOrEqual(0);
    expect(scale.zero).toBeLessThanOrEqual(1);
  });

  it('erosion is the distance inflation took out of the nominal figure', () => {
    const scale = buildDeflation([fund('AAA', 0.315, -0.002)], '1y');
    expect(scale.rows[0].erosion).toBeCloseTo(0.317, 5);
  });
});

describe('positionOf', () => {
  it('preserves order, so a larger return never plots to the left of a smaller one', () => {
    const scale = buildDeflation(
      [fund('A', 13, 9.6), fund('B', 1.04, 0.55), fund('C', 0.3, -0.1)],
      '1y'
    );
    expect(positionOf(scale, 1.04)).toBeGreaterThanOrEqual(positionOf(scale, 0.3));
    expect(positionOf(scale, 0.3)).toBeGreaterThan(positionOf(scale, -0.1));
  });

  it('spreads the small end that a linear axis would collapse', () => {
    const scale = buildDeflation(
      [fund('A', 13, 9.6), fund('B', 0.6, 0.2), fund('C', 0.3, -0.1)],
      '1y'
    );
    // On a linear axis 0.3 and 0.6 sit 2.3% apart against a 13.1 span; the
    // compressed axis has to separate them by an order of magnitude more.
    expect(positionOf(scale, 0.6) - positionOf(scale, 0.3)).toBeGreaterThan(0.05);
  });

  it('clamps values outside the built domain', () => {
    const scale = buildDeflation([fund('A', 0.5, 0.2)], '1y');
    expect(positionOf(scale, 99)).toBe(1);
    expect(positionOf(scale, -99)).toBe(0);
  });

  it('puts zero exactly on the reported zero line', () => {
    const scale = buildDeflation([fund('A', 0.5, -0.2)], '1y');
    expect(positionOf(scale, 0)).toBeCloseTo(scale.zero, 10);
  });
});
