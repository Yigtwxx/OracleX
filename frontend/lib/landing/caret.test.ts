import { describe, expect, it } from 'vitest';
import { rollCaret } from './caret';

/**
 * The caret's body is positioned by two CSS custom properties as percentages of
 * the wick. Nothing in the stylesheet clamps them, so a roll that returned a
 * body starting at 0.8 and 0.5 tall would draw a candle hanging out of its own
 * wick. Five hundred draws is enough to catch a bound that is off by an
 * arithmetic slip rather than by luck.
 */
describe('rollCaret', () => {
  const draws = Array.from({ length: 500 }, () => rollCaret());

  it('keeps the body inside the wick', () => {
    for (const caret of draws) {
      expect(caret.bodyTop).toBeGreaterThanOrEqual(0);
      expect(caret.bodyHeight).toBeGreaterThan(0);
      expect(caret.bodyTop + caret.bodyHeight).toBeLessThanOrEqual(1);
    }
  });

  it('only ever draws a direction the stylesheet has a colour for', () => {
    for (const caret of draws) expect(['up', 'down']).toContain(caret.tone);
  });

  it('draws both directions and more than one body size — a caret, not a blink', () => {
    expect(new Set(draws.map((caret) => caret.tone)).size).toBe(2);
    expect(new Set(draws.map((caret) => caret.bodyHeight)).size).toBeGreaterThan(1);
  });
});
