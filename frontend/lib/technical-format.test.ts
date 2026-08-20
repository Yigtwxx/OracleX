import { describe, it, expect } from 'vitest';
import {
  confirmedOn,
  formatBand,
  formatLevel,
  formatSignedPercent,
  horizonLabel,
  rangeFraction,
  rsiTone,
  slopeMark,
  trendTone,
  UNKNOWN,
} from './technical-format';
import type { PriceZone } from '@/store/useStore';

function zone(partial: Partial<PriceZone> = {}): PriceZone {
  return {
    low: 100,
    high: 102,
    mid: 101,
    touches: 3,
    flip: false,
    strength: 70,
    horizon: 'medium',
    timeframe: '1d',
    timeframes: ['1d'],
    confluence: [],
    distance_percent: -1.5,
    ...partial,
  };
}

describe('formatLevel', () => {
  it('drops decimals a five-figure price does not carry', () => {
    expect(formatLevel(64294.5)).toBe('$64,295');
  });

  it('keeps the precision a sub-dollar token needs', () => {
    // Rounded to two decimals this reads as $0.00, which is not a price.
    expect(formatLevel(0.00031)).toBe('$0.00031000');
    expect(formatLevel(1.2345)).toBe('$1.23');
  });
});

describe('formatBand', () => {
  it('renders both bounds, because both were measured', () => {
    expect(formatBand({ low: 61830, high: 63237.6 })).toBe('$61,830 – $63,238');
  });

  it('collapses a band that came from a single reversal', () => {
    // "$100 – $100" would suggest a width that was never measured.
    expect(formatBand({ low: 100, high: 100 })).toBe('$100.00');
  });
});

describe('formatSignedPercent', () => {
  it('always carries the sign, so direction never depends on colour alone', () => {
    expect(formatSignedPercent(2.85)).toBe('+2.9%');
    expect(formatSignedPercent(-1.22)).toBe('-1.2%');
    expect(formatSignedPercent(0)).toBe('+0.0%');
  });

  it('says nothing rather than zero when there is no reading', () => {
    expect(formatSignedPercent(null)).toBe(UNKNOWN);
    expect(formatSignedPercent(undefined)).toBe(UNKNOWN);
    expect(formatSignedPercent(Number.NaN)).toBe(UNKNOWN);
  });
});

describe('confirmedOn', () => {
  it('names every timeframe that found the band', () => {
    expect(confirmedOn(zone({ timeframes: ['1d', '1w', '4h'] }))).toBe('1d+1w+4h');
  });

  it('falls back to the single timeframe on an older payload', () => {
    expect(confirmedOn(zone({ timeframes: [], timeframe: '4h' }))).toBe('4h');
  });
});

describe('tones', () => {
  it('maps trend to the semantic palette', () => {
    expect(trendTone('bullish')).toBe('up');
    expect(trendTone('bearish')).toBe('down');
    expect(trendTone('neutral')).toBe('warn');
    expect(trendTone(null)).toBe('muted');
  });

  it('treats both RSI extremes as stretched rather than good or bad', () => {
    // Overbought is not bullish news and oversold is not bearish news; borrowing
    // the up/down palette here would say the opposite of what it means.
    expect(rsiTone({ value: 78 })).toBe('warn');
    expect(rsiTone({ value: 22 })).toBe('warn');
    expect(rsiTone({ value: 64 })).toBe('up');
    expect(rsiTone({ value: 36 })).toBe('down');
    expect(rsiTone({ value: 50 })).toBe('muted');
    expect(rsiTone(undefined)).toBe('muted');
  });

  it('marks slope with an arrow that is never the only signal', () => {
    expect(slopeMark('rising')).toBe('↑');
    expect(slopeMark('falling')).toBe('↓');
    expect(slopeMark('flat')).toBe('→');
    expect(slopeMark(null)).toBe('');
  });
});

describe('horizonLabel', () => {
  it('labels the known horizons and passes anything else through', () => {
    expect(horizonLabel('short')).toBe('Short');
    expect(horizonLabel('long')).toBe('Long');
    expect(horizonLabel('weekly-ish')).toBe('weekly-ish');
  });
});

describe('rangeFraction', () => {
  it('places price inside its range', () => {
    expect(rangeFraction(60, 40, 140)).toBeCloseTo(0.2);
  });

  it('clamps a price that printed outside the trailing range', () => {
    expect(rangeFraction(200, 40, 140)).toBe(1);
    expect(rangeFraction(10, 40, 140)).toBe(0);
  });

  it('returns null rather than a midpoint when the range is unknown', () => {
    // A marker on an undrawable bar reads as a measurement.
    expect(rangeFraction(60, null, 140)).toBeNull();
    expect(rangeFraction(60, 100, 100)).toBeNull();
  });
});
