import { describe, expect, it } from 'vitest';
import { BTC_SERIES, buildSeries, CANDLE_COUNT, REGIME_BOUNDS } from './candle-series';

describe('buildSeries', () => {
  it('is deterministic for a given seed', () => {
    expect(buildSeries(12345)).toEqual(buildSeries(12345));
  });

  it('produces a different tape for a different seed', () => {
    expect(buildSeries(1)).not.toEqual(buildSeries(2));
  });

  it('emits exactly CANDLE_COUNT candles', () => {
    expect(BTC_SERIES.candles).toHaveLength(CANDLE_COUNT);
  });

  it('holds the OHLC invariants on every candle', () => {
    BTC_SERIES.candles.forEach((candle, i) => {
      expect(candle.h, `candle ${i} high`).toBeGreaterThanOrEqual(Math.max(candle.o, candle.c));
      expect(candle.l, `candle ${i} low`).toBeLessThanOrEqual(Math.min(candle.o, candle.c));
      expect(candle.l, `candle ${i} low`).toBeGreaterThan(0);
    });
  });

  it('contains no NaN or Infinity', () => {
    for (const candle of BTC_SERIES.candles) {
      for (const value of [candle.o, candle.h, candle.l, candle.c, candle.v]) {
        expect(Number.isFinite(value)).toBe(true);
      }
    }
  });

  it('reports the true maximum volume', () => {
    const observed = Math.max(...BTC_SERIES.candles.map((c) => c.v));
    expect(BTC_SERIES.maxVolume).toBeCloseTo(observed, 10);
  });

  it('opens each candle at the previous close', () => {
    for (let i = 1; i < BTC_SERIES.candles.length; i += 1) {
      expect(BTC_SERIES.candles[i].o).toBeCloseTo(BTC_SERIES.candles[i - 1].c, 10);
    }
  });
});

describe('REGIME_BOUNDS', () => {
  it('tiles the series without gaps or overlaps', () => {
    expect(REGIME_BOUNDS[0].start).toBe(0);
    expect(REGIME_BOUNDS[REGIME_BOUNDS.length - 1].end).toBe(CANDLE_COUNT - 1);
    for (let i = 1; i < REGIME_BOUNDS.length; i += 1) {
      expect(REGIME_BOUNDS[i].start).toBe(REGIME_BOUNDS[i - 1].end + 1);
    }
  });

  it('tells the intended story — the tape rises, tops, breaks, then recovers', () => {
    const closeAt = (i: number) => BTC_SERIES.candles[i].c;
    const [accumulation, impulse, , , blowoff, , capitulation, recovery] = REGIME_BOUNDS;

    expect(closeAt(impulse.end)).toBeGreaterThan(closeAt(accumulation.end));
    expect(closeAt(blowoff.end)).toBeGreaterThan(closeAt(impulse.end));
    expect(closeAt(capitulation.end)).toBeLessThan(closeAt(blowoff.end));
    expect(closeAt(recovery.end)).toBeGreaterThan(closeAt(capitulation.end));
  });
});
