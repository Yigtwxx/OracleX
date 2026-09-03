import { describe, expect, it } from 'vitest';

import type { LiquidationLine } from './api';
import {
  bubbleRadius,
  BUCKETS,
  filterLines,
  leverageBucket,
  lineAlpha,
  maxNotional,
  topByNotional,
  type LeverageBucket,
} from './liquidation-lines';

/** `[start, end, bin, leverage, side, notional]`. */
function span(leverage: number, notional = 100): LiquidationLine {
  return [0, 10, 50, leverage, 0, notional];
}

describe('leverageBucket', () => {
  it.each([
    [5, 'low'],
    [10, 'low'],
    [24, 'low'],
    [25, 'medium'],
    [49, 'medium'],
    [50, 'high'],
    [100, 'high'],
  ])('puts %dx in the %s band', (leverage, expected) => {
    expect(leverageBucket(leverage)).toBe(expected);
  });

  it('places a tier the backend adds later without dropping it', () => {
    // Ranges rather than an exhaustive map: a new 75x tier has to land
    // somewhere, and silently belonging to no band would hide it from every
    // filter at once.
    expect(BUCKETS).toContain(leverageBucket(75));
    expect(BUCKETS).toContain(leverageBucket(3));
  });
});

describe('filterLines', () => {
  const lines = [span(10), span(25), span(50), span(100)];

  it('returns the same array when every band is on', () => {
    // Identity, not equality: the common case must not rebuild the array on
    // every render of a chart holding thousands of spans.
    expect(filterLines(lines, new Set(BUCKETS))).toBe(lines);
  });

  it('keeps only the enabled bands', () => {
    const high = filterLines(lines, new Set<LeverageBucket>(['high']));
    expect(high.map((line) => line[3])).toEqual([50, 100]);
  });

  it('returns nothing when no band is enabled', () => {
    expect(filterLines(lines, new Set<LeverageBucket>())).toEqual([]);
  });
});

describe('lineAlpha', () => {
  it('gives a tier peak full opacity', () => {
    expect(lineAlpha(500, 500)).toBeCloseTo(1);
  });

  it('never drops a span to invisible', () => {
    expect(lineAlpha(0, 500)).toBeGreaterThan(0);
  });

  it('rises with notional', () => {
    expect(lineAlpha(400, 500)).toBeGreaterThan(lineAlpha(100, 500));
  });

  it('scales against the tier, not the whole chart', () => {
    // The 100x band's peak is a fraction of the 10x band's. Scaled globally the
    // whole band would render faint, and switching the filter to high-leverage
    // only would look like a rendering fault rather than a filter.
    expect(lineAlpha(1_000, 1_000)).toBeCloseTo(lineAlpha(10_000, 10_000));
  });

  it('survives an empty tier', () => {
    expect(Number.isFinite(lineAlpha(0, 0))).toBe(true);
  });
});

describe('maxNotional', () => {
  it('finds the largest span', () => {
    expect(maxNotional([span(10, 100), span(50, 900), span(25, 400)])).toBe(900);
  });

  it('answers zero for an empty book rather than -Infinity', () => {
    // `Math.max()` with no arguments would, and it feeds a divisor.
    expect(maxNotional([])).toBe(0);
  });
});

describe('bubbleRadius', () => {
  it('draws area, not radius, in proportion to notional', () => {
    // Four times the notional has to read as twice as wide, or the top of the
    // book looks an order of magnitude heavier than it is.
    const largest = 10_000;
    const small = bubbleRadius(2_500, largest);
    const big = bubbleRadius(10_000, largest);
    const floor = bubbleRadius(0, largest);
    expect(big - floor).toBeCloseTo((small - floor) * 2);
  });

  it('keeps the tail visible', () => {
    expect(bubbleRadius(1, 10_000_000)).toBeGreaterThan(1);
  });

  it('rises with notional', () => {
    expect(bubbleRadius(900, 1_000)).toBeGreaterThan(bubbleRadius(100, 1_000));
  });

  it('clamps a span that exceeds the reference', () => {
    expect(bubbleRadius(5_000, 1_000)).toBe(bubbleRadius(1_000, 1_000));
  });

  it('survives an empty book', () => {
    expect(Number.isFinite(bubbleRadius(100, 0))).toBe(true);
  });
});

describe('topByNotional', () => {
  const book = [span(10, 100), span(50, 900), span(25, 400), span(100, 700)];

  it('returns the heaviest first', () => {
    expect(topByNotional(book, 2).map((line) => line[5])).toEqual([900, 700]);
  });

  it("leaves the caller's array alone", () => {
    const order = book.map((line) => line[5]);
    topByNotional(book, 4);
    expect(book.map((line) => line[5])).toEqual(order);
  });

  it('returns everything when the book is shorter than the limit', () => {
    expect(topByNotional(book, 99)).toHaveLength(4);
  });
});
