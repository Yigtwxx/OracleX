import type { CSSProperties } from 'react';

/**
 * The waiting indicator for Oracle: a short candlestick series that prints one
 * candle at a time and then clears itself in the same order, on a loop.
 *
 * A generic spinner says only "something is happening". This says what is
 * happening — the model is reading the tape — using the two colours the rest of
 * the terminal already spends on direction, so nothing new has to be learned to
 * read it.
 *
 * The bars are a fixed, hand-placed series rather than random values: a loader
 * that reshuffles every cycle reads as data arriving, and no data is arriving.
 */

interface Candle {
  direction: 'up' | 'down';
  /** All offsets are px within the 18px track, measured from the top. */
  wickTop: number;
  wickHeight: number;
  bodyTop: number;
  bodyHeight: number;
}

const CANDLES: Candle[] = [
  { direction: 'down', wickTop: 5, wickHeight: 12, bodyTop: 8, bodyHeight: 7 },
  { direction: 'up', wickTop: 2, wickHeight: 14, bodyTop: 5, bodyHeight: 9 },
  { direction: 'up', wickTop: 0, wickHeight: 13, bodyTop: 2, bodyHeight: 8 },
  { direction: 'down', wickTop: 1, wickHeight: 12, bodyTop: 4, bodyHeight: 6 },
  { direction: 'up', wickTop: 0, wickHeight: 15, bodyTop: 1, bodyHeight: 10 },
  { direction: 'down', wickTop: 3, wickHeight: 13, bodyTop: 6, bodyHeight: 7 },
];

/**
 * Gap between one candle starting its cycle and the next. The whole series is
 * one keyframe offset per candle, so the print and the clear are staggered by
 * the same amount and stay in step for as long as the loop runs.
 */
const STAGGER_MS = 90;

export default function ThinkingCandles() {
  return (
    <div className="thinking-candles" aria-hidden>
      {CANDLES.map((candle, index) => (
        <span
          key={index}
          className={`thinking-candle ${candle.direction === 'up' ? 'is-up' : 'is-down'}`}
          style={
            {
              animationDelay: `${index * STAGGER_MS}ms`,
              '--wick-top': `${candle.wickTop}px`,
              '--wick-h': `${candle.wickHeight}px`,
              '--body-top': `${candle.bodyTop}px`,
              '--body-h': `${candle.bodyHeight}px`,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}
