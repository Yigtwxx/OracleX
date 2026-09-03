/**
 * The board's arrays carry holes, and every derivation here has to keep them.
 *
 * A `null` means a venue did not report that bar. Collapsing one to zero is the
 * failure worth guarding: the delta pane would draw a -100% crash where an
 * exchange merely went quiet, the ratio pane would draw a floor, and the
 * tooltip's shares would stop summing. None of those look like bugs on screen,
 * which is exactly why they are tested here rather than left to the chart.
 */

import { describe, it, expect } from 'vitest';

import {
  aggregateChangePct,
  oiToMarketCapRatio,
  venueShare,
  windowSummary,
  withAlpha,
} from './open-interest';

describe('aggregateChangePct', () => {
  it('reports the percentage step from the previous bar', () => {
    expect(aggregateChangePct([100, 110, 99])).toEqual([null, 10, -10]);
  });

  it('leaves a hole on either side of a missing bar', () => {
    // Bridging the gap would invent a two-bar move the data never showed.
    expect(aggregateChangePct([100, null, 121])).toEqual([null, null, null]);
  });

  it('refuses to divide by a zero baseline', () => {
    expect(aggregateChangePct([0, 50])).toEqual([null, null]);
  });

  it('honours a longer lookback', () => {
    expect(aggregateChangePct([100, 200, 150], 2)).toEqual([null, null, 50]);
  });
});

describe('oiToMarketCapRatio', () => {
  it('expresses open interest as a percentage of market cap', () => {
    expect(oiToMarketCapRatio([40, 60], [1000, 1000])).toEqual([4, 6]);
  });

  it('yields nothing at all when supply was unknown', () => {
    // An empty market_cap array is a missing pane, not a zero ratio.
    expect(oiToMarketCapRatio([40, 60], [])).toEqual([null, null]);
  });

  it('keeps a hole where the aggregate has one', () => {
    expect(oiToMarketCapRatio([null, 60], [1000, 1000])).toEqual([null, 6]);
  });
});

describe('venueShare', () => {
  const venues = ['Binance', 'OKX', 'Bybit'];

  it('splits a bar across the venues that reported', () => {
    const series = { Binance: [50], OKX: [30], Bybit: [20] };
    const shares = venueShare(series, venues, 0);

    expect(shares.map((entry) => entry.venue)).toEqual(venues);
    expect(shares.map((entry) => entry.share)).toEqual([50, 30, 20]);
  });

  it('still sums to 100% when a venue is missing that bar', () => {
    const series = { Binance: [50], OKX: [null], Bybit: [50] };
    const shares = venueShare(series, venues, 0);

    expect(shares.map((entry) => entry.venue)).toEqual(['Binance', 'Bybit']);
    expect(shares.reduce((sum, entry) => sum + entry.share, 0)).toBe(100);
  });

  it('returns nothing for a bar no venue reported', () => {
    expect(venueShare({ Binance: [null] }, ['Binance'], 0)).toEqual([]);
  });

  it('handles a board with a single venue', () => {
    const shares = venueShare({ Binance: [42] }, ['Binance'], 0);
    expect(shares).toEqual([{ venue: 'Binance', value: 42, share: 100 }]);
  });
});

describe('windowSummary', () => {
  it('measures from the first reported bar to the last', () => {
    expect(windowSummary([100, 120, 150])).toEqual({
      first: 100,
      latest: 150,
      changePct: 50,
    });
  });

  it('skips leading and trailing holes rather than reading them as flat', () => {
    // A window opening on a gap must not report "no change" — that is the one
    // answer that is certainly wrong.
    expect(windowSummary([null, 100, 200, null])).toEqual({
      first: 100,
      latest: 200,
      changePct: 100,
    });
  });

  it('reports nothing for an empty board', () => {
    expect(windowSummary([])).toEqual({ first: null, latest: null, changePct: null });
    expect(windowSummary([null, null])).toEqual({
      first: null,
      latest: null,
      changePct: null,
    });
  });
});

describe('withAlpha', () => {
  it('converts a six-digit hex', () => {
    expect(withAlpha('#3ecf8e', 0.45)).toBe('rgba(62, 207, 142, 0.45)');
  });

  it('expands a three-digit hex', () => {
    expect(withAlpha('#fff', 1)).toBe('rgba(255, 255, 255, 1)');
  });

  it('passes a value it cannot parse through untouched', () => {
    // readPalette() can hand back an rgba() token; better a wrong opacity than
    // a series that renders as nothing.
    expect(withAlpha('rgba(1, 2, 3, 0.5)', 0.4)).toBe('rgba(1, 2, 3, 0.5)');
  });
});
