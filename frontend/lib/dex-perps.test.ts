import { describe, expect, it } from 'vitest';

import type { DexPerpVenue } from './api';
import { logFloor, rampColors, shareOfTotal, TOP_N, topVenues } from './dex-perps';

function venue(name: string, value: number): DexPerpVenue {
  return {
    slug: name.toLowerCase(),
    name,
    value_usd: value,
    change_1d_pct: null,
    logo: '',
    chains: [],
  };
}

const RANKED = [venue('A', 100), venue('B', 50), venue('C', 25)];

describe('topVenues', () => {
  it('keeps the leaders in the order the backend ranked them', () => {
    expect(topVenues(RANKED, 2).map((v) => v.name)).toEqual(['A', 'B']);
  });

  it('returns everything when the list is shorter than the cut', () => {
    expect(topVenues(RANKED, 10)).toHaveLength(3);
  });

  it('defaults to the panel cut', () => {
    const many = Array.from({ length: 40 }, (_, i) => venue(`V${i}`, 40 - i));
    expect(topVenues(many)).toHaveLength(TOP_N);
  });

  it('survives an empty panel', () => {
    expect(topVenues([])).toEqual([]);
  });
});

describe('shareOfTotal', () => {
  it('divides each venue by the sum of the rows passed in', () => {
    expect(shareOfTotal(RANKED)).toEqual([100 / 175, 50 / 175, 25 / 175]);
  });

  it('sums to one', () => {
    const total = shareOfTotal(RANKED).reduce((sum, share) => sum + share, 0);
    expect(total).toBeCloseTo(1, 10);
  });

  it('survives an empty panel', () => {
    expect(shareOfTotal([])).toEqual([]);
  });
});

describe('logFloor', () => {
  it('sits below the smallest bar so the axis has room under it', () => {
    expect(logFloor(RANKED)).toBe(12.5);
  });

  it('is positive for an empty panel, because a log axis cannot start at zero', () => {
    expect(logFloor([])).toBeGreaterThan(0);
  });
});

describe('rampColors', () => {
  const STOPS = ['#000000', '#ffffff'];

  it('gives every bar its own colour', () => {
    const colors = rampColors(5, STOPS);
    expect(new Set(colors).size).toBe(5);
  });

  it('starts and ends on the stops it was given', () => {
    const colors = rampColors(3, STOPS);
    expect(colors[0]).toBe('rgb(0, 0, 0)');
    expect(colors[2]).toBe('rgb(255, 255, 255)');
  });

  it('reaches the last stop rather than stopping one pair short', () => {
    // Three stops is where an unclamped index would run off the end.
    const colors = rampColors(4, ['#000000', '#808080', '#ffffff']);
    expect(colors[3]).toBe('rgb(255, 255, 255)');
  });

  it('survives an empty panel and a panel of one', () => {
    expect(rampColors(0, STOPS)).toEqual([]);
    expect(rampColors(1, STOPS)).toEqual(['rgb(0, 0, 0)']);
  });

  it('ignores stops that are not hex colours', () => {
    // A palette token can come back as an rgb() string or empty when the
    // document has not been read yet; a NaN channel would paint nothing.
    expect(rampColors(2, ['rgb(1, 2, 3)', ''])).toEqual([]);
  });
});
