import { describe, expect, it } from 'vitest';

import {
  bucketState,
  coverage,
  edgePoints,
  formatEdge,
  formatPct,
  formatRate,
  horizonLabel,
  isEmpty,
  observedMix,
  type TrackRecordSummary,
} from './trackRecord';

describe('formatRate', () => {
  it('renders a rate as a percentage', () => {
    expect(formatRate(0.2941)).toBe('29%');
    expect(formatRate(1)).toBe('100%');
  });

  it('renders a withheld rate as an absence, never as zero', () => {
    // The backend returns null when the sample is too small to state a rate.
    // Printing 0% for that would turn a refusal into the worst possible claim.
    expect(formatRate(null)).toBe('—');
    expect(formatRate(undefined)).toBe('—');
    expect(formatRate(Number.NaN)).toBe('—');
  });

  it('keeps a genuine zero distinct from a missing one', () => {
    expect(formatRate(0)).toBe('0%');
  });
});

describe('bucketState', () => {
  it('separates "nothing scored" from "not enough to state"', () => {
    expect(bucketState({ n: 0, hit_rate: null })).toBe('unscored');
    expect(bucketState({ n: 4, hit_rate: null })).toBe('too-few');
    expect(bucketState({ n: 12, hit_rate: 0.5 })).toBe('reported');
  });
});

describe('edgePoints', () => {
  it('measures the gap against the best fixed answer', () => {
    expect(edgePoints({ hit_rate: 0.62, baseline_rate: 0.5 })).toBe(12);
    expect(edgePoints({ hit_rate: 0.3, baseline_rate: 0.55 })).toBe(-25);
  });

  it('refuses when either side was withheld', () => {
    // Reading the missing benchmark as zero would report the whole hit rate as
    // edge — the single most flattering mistake available on this page.
    expect(edgePoints({ hit_rate: 0.8, baseline_rate: null })).toBeNull();
    expect(edgePoints({ hit_rate: null, baseline_rate: 0.5 })).toBeNull();
    expect(edgePoints({ hit_rate: 0.8, baseline_rate: undefined })).toBeNull();
  });
});

describe('formatEdge', () => {
  it('signs the gap and names a tie', () => {
    expect(formatEdge(12)).toBe('+12.0 pts');
    expect(formatEdge(-25)).toBe('−25.0 pts');
    expect(formatEdge(0)).toBe('level');
    expect(formatEdge(null)).toBe('—');
  });
});

describe('formatPct', () => {
  it('signs a price move and keeps one decimal', () => {
    expect(formatPct(17.04)).toBe('+17.0%');
    expect(formatPct(-3.26)).toBe('-3.3%');
    // Math.round breaks a .5 tie toward positive infinity, so a negative half
    // rounds toward zero. Pinned rather than worked around: it is a tenth of a
    // percentage point on a figure already labelled as a measurement.
    expect(formatPct(-3.25)).toBe('-3.2%');
    expect(formatPct(null)).toBe('—');
  });
});

describe('horizonLabel', () => {
  it('reads long horizons as durations', () => {
    expect(horizonLabel(1)).toBe('1d');
    expect(horizonLabel(7)).toBe('7d');
    expect(horizonLabel(30)).toBe('1mo');
    expect(horizonLabel(90)).toBe('3mo');
    expect(horizonLabel(365)).toBe('1y');
  });
});

describe('observedMix', () => {
  it('divides by its own count rather than a borrowed one', () => {
    const mix = observedMix({ horizon_days: 1, n: 4, bullish: 3, bearish: 1, neutral: 0 });
    expect(mix).toEqual({ bullish: 0.75, bearish: 0.25, neutral: 0 });
  });

  it('is null with nothing measured', () => {
    expect(observedMix({ horizon_days: 1, n: 0, bullish: 0, bearish: 0, neutral: 0 })).toBeNull();
  });
});

describe('coverage', () => {
  it('counts the due-but-unmeasured horizons in the denominator', () => {
    // Dropping `pending` would report a record that is always complete.
    expect(
      coverage({
        predictions: 9,
        predictions_scored: 9,
        measured: 60,
        unmeasurable: 0,
        pending: 20,
      })
    ).toBe(0.75);
  });

  it('is null before anything has come due', () => {
    expect(
      coverage({ predictions: 2, predictions_scored: 0, measured: 0, unmeasurable: 0, pending: 0 })
    ).toBeNull();
  });
});

describe('isEmpty', () => {
  const summary = (measured: number): TrackRecordSummary =>
    ({
      totals: { predictions: 5, predictions_scored: 1, measured, unmeasurable: 0, pending: 3 },
    }) as TrackRecordSummary;

  it('is empty until something has actually been measured', () => {
    expect(isEmpty(undefined)).toBe(true);
    expect(isEmpty(summary(0))).toBe(true);
    expect(isEmpty(summary(1))).toBe(false);
  });
});
