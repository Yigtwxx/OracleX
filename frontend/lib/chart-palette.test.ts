import { describe, expect, it } from 'vitest';

import { compactUsd, FALLBACK, parseHex, TOKENS } from './chart-palette';

describe('parseHex', () => {
  it('expands three-digit shorthand', () => {
    expect(parseHex('#f0a')).toEqual([255, 0, 170]);
  });

  it('reads six-digit hex', () => {
    expect(parseHex('#4788ff')).toEqual([71, 136, 255]);
  });

  it('does not require the leading hash', () => {
    expect(parseHex('22c55e')).toEqual(parseHex('#22c55e'));
  });
});

describe('compactUsd', () => {
  // The boundaries are where a wrong comparison hides: 999 must not become
  // "$1K" and 1000 must not stay "$1000".
  it.each([
    [0, '$0'],
    [999, '$999'],
    [1_000, '$1K'],
    [999_999, '$1000K'],
    [1_000_000, '$1.0M'],
    [1_000_000_000, '$1.00B'],
  ])('formats %d as %s', (value, expected) => {
    expect(compactUsd(value)).toBe(expected);
  });

  it('keeps the sign on negative values', () => {
    // toFixed rounds away from zero, so -2.5K reads as -3K.
    expect(compactUsd(-2_500)).toBe('$-3K');
  });
});

describe('FALLBACK', () => {
  // A missing entry would render as `undefined` on the canvas, which draws
  // nothing at all rather than failing loudly.
  it('covers every token the charts ask for', () => {
    for (const token of TOKENS) {
      expect(FALLBACK[token]).toBeTruthy();
    }
  });
});
