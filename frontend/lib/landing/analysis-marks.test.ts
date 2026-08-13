import { describe, expect, it } from 'vitest';
import { ANALYSIS_MARKS, maxIndexOf } from './analysis-marks';
import { CANDLE_COUNT } from './candle-series';
import { progressOfCandle } from './stages';

describe('ANALYSIS_MARKS', () => {
  /**
   * The load-bearing test. A mark that reveals before the candles it draws on
   * have printed is a Fibonacci retracement floating over blank space — the one
   * failure that makes the whole scene read as decoration rather than analysis.
   */
  it('never reveals a mark before the candles it references have printed', () => {
    for (const { from, mark } of ANALYSIS_MARKS) {
      const maxIndex = maxIndexOf(mark);
      if (maxIndex < 0) continue;
      const printed = progressOfCandle(maxIndex, CANDLE_COUNT);
      expect(from, `${mark.kind} @ candle ${maxIndex}`).toBeGreaterThanOrEqual(printed - 1e-12);
    }
  });

  it('keeps every referenced index inside the series', () => {
    for (const { mark } of ANALYSIS_MARKS) {
      const maxIndex = maxIndexOf(mark);
      expect(maxIndex).toBeLessThan(CANDLE_COUNT);
      expect(maxIndex).toBeGreaterThanOrEqual(-1);
    }
  });

  it('gives every mark a forward-running reveal window inside [0, 1]', () => {
    for (const { from, to, mark } of ANALYSIS_MARKS) {
      expect(to, mark.kind).toBeGreaterThan(from);
      expect(from, mark.kind).toBeGreaterThanOrEqual(0);
      expect(from, mark.kind).toBeLessThanOrEqual(1);
    }
  });

  it('draws ranged marks left to right', () => {
    for (const { mark } of ANALYSIS_MARKS) {
      if ('from' in mark && 'to' in mark && typeof mark.from === 'number') {
        expect(mark.to, mark.kind).toBeGreaterThan(mark.from);
      }
    }
  });

  it('covers every annotated stage', () => {
    // Four feature panels, so the scene must have something to say during each.
    expect(ANALYSIS_MARKS.length).toBeGreaterThanOrEqual(8);
  });
});
