import { describe, expect, it } from 'vitest';
import {
  RATIO_CAP,
  UNKNOWN,
  dialPosition,
  formatIndex,
  hasReading,
  statusCaption,
} from './pizza-index';

describe('dialPosition', () => {
  it('puts a normal reading at dead centre', () => {
    expect(dialPosition(1)).toBe(0);
  });

  it('places equal-and-opposite ratios equidistant from centre', () => {
    // Half as busy and twice as busy are the same size of departure from usual.
    // On a linear scale they would not be, and the gauge would imply that
    // "quiet" is a smaller deviation than "busy".
    const half = dialPosition(0.5)!;
    const double = dialPosition(2)!;
    expect(half).toBeCloseTo(-double, 10);
  });

  it('reaches the ends exactly at the cap', () => {
    expect(dialPosition(RATIO_CAP)).toBeCloseTo(1, 10);
    expect(dialPosition(1 / RATIO_CAP)).toBeCloseTo(-1, 10);
  });

  it('clamps beyond the cap rather than running off the track', () => {
    expect(dialPosition(50)).toBe(1);
    expect(dialPosition(0.001)).toBe(-1);
  });

  it('has no position for a missing or impossible reading', () => {
    // Not 0 — parking the marker at centre would render an absent reading as a
    // measured "normal".
    expect(dialPosition(null)).toBeNull();
    expect(dialPosition(0)).toBeNull();
    expect(dialPosition(-1)).toBeNull();
  });
});

describe('formatIndex', () => {
  it('writes the reading as a multiple, never as a score', () => {
    expect(formatIndex(1.42)).toBe('1.4×');
    expect(formatIndex(1)).toBe('1.0×');
  });

  it('drops the decimal once it stops carrying information', () => {
    expect(formatIndex(12.4)).toBe('12×');
  });

  it('shows a dash rather than a zero for a missing reading', () => {
    expect(formatIndex(null)).toBe(UNKNOWN);
  });
});

describe('hasReading', () => {
  it('separates the two null-index states', () => {
    expect(hasReading('normal')).toBe(true);
    expect(hasReading('spike')).toBe(true);
    expect(hasReading('insufficient_data')).toBe(false);
    expect(hasReading('unavailable')).toBe(false);
  });
});

describe('statusCaption', () => {
  it('distinguishes closed venues from an unreadable source', () => {
    expect(statusCaption('insufficient_data', 2)).toContain('too few to score');
    expect(statusCaption('unavailable', 0)).toContain('could not be reached');
  });

  it('says nothing was reporting when nothing was', () => {
    expect(statusCaption('insufficient_data', 0)).toContain('closed');
  });

  it('agrees in number with the venue count', () => {
    expect(statusCaption('normal', 1)).toContain('1 venue ');
    expect(statusCaption('normal', 4)).toContain('4 venues ');
  });
});
