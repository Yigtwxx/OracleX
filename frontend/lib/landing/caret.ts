/**
 * The write head, as a candle.
 *
 * Extracted from `TypedPoints` because it now has a second caller: the section
 * spine on the documentation pages marks your position with the same glyph, and
 * crossing a section boundary prints a new candle exactly as typing a character
 * does. One roll, one look — two implementations would drift into two.
 */

export interface Caret {
  readonly tone: 'up' | 'down';
  /** Where the body starts inside the wick, and how much of it the body is. */
  readonly bodyTop: number;
  readonly bodyHeight: number;
}

/**
 * A new candle for the write head.
 *
 * Direction, body size and where the body sits on the wick are all independent
 * draws, because a caret that only flipped colour would read as a two-frame
 * blink rather than as a tape printing.
 *
 * Random, so it must only ever be called from an effect or an event handler.
 * Calling it during render would give the server and the client two different
 * candles and cost a hydration mismatch.
 */
export function rollCaret(): Caret {
  const bodyHeight = 0.22 + Math.random() * 0.44;
  return {
    tone: Math.random() < 0.5 ? 'up' : 'down',
    bodyTop: Math.random() * (1 - bodyHeight),
    bodyHeight,
  };
}
