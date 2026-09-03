import { describe, expect, it } from 'vitest';
import {
  BANDS,
  UNKNOWN,
  bandPosition,
  formatIndex,
  formatProbability,
  hasReading,
  markerShift,
  trackFill,
} from './neh-index';

describe('bandPosition', () => {
  it('gives every band an equal quarter of the track', () => {
    // Not to scale on purpose: drawn proportionally, "It Happened" would be a
    // two-point sliver and the marker would never visibly enter it.
    expect(bandPosition(0)).toBe(0);
    expect(bandPosition(29)).toBe(25);
    expect(bandPosition(30)).toBe(25);
    expect(bandPosition(64)).toBe(50);
    expect(bandPosition(65)).toBe(50);
    expect(bandPosition(98)).toBe(75);
    expect(bandPosition(99)).toBe(75);
    expect(bandPosition(100)).toBe(100);
  });

  it('moves monotonically as the reading rises', () => {
    const positions = [0, 10, 29, 30, 50, 64, 65, 80, 98, 99, 100].map(
      (index) => bandPosition(index)!
    );
    const sorted = [...positions].sort((a, b) => a - b);
    expect(positions).toEqual(sorted);
  });

  it('clamps a reading outside 0–100 rather than running off the track', () => {
    expect(bandPosition(140)).toBe(100);
    expect(bandPosition(-5)).toBe(0);
  });

  it('reports no position for a missing reading', () => {
    // Null, not 0 — parking the marker at the left edge would render an outage
    // as a measured calm, which is the one reading this gauge must not invent.
    expect(bandPosition(null)).toBeNull();
  });
});

describe('trackFill', () => {
  it('stops the fill under the marker instead of a band past it', () => {
    // The bug this replaced: a reading of 30 sits at the first point of
    // "Something Might Happen", so the marker stands at a quarter of the track
    // — but lighting the whole band it had just entered filled half of it.
    const fill = trackFill(bandPosition(30));
    expect(fill).toEqual({ band: 1, within: 0 });
  });

  it('fills the band it is partway through in proportion', () => {
    expect(trackFill(37.5)).toEqual({ band: 1, within: 50 });
    expect(trackFill(12.5)).toEqual({ band: 0, within: 50 });
  });

  it('keeps a full reading inside the last band rather than one past the end', () => {
    expect(trackFill(100)).toEqual({ band: 3, within: 100 });
  });

  it('leaves the track unlit when there is no reading', () => {
    expect(trackFill(null)).toEqual({ band: -1, within: 0 });
  });
});

describe('markerShift', () => {
  it('pins the marker inside the track at both ends', () => {
    // Half a marker hanging past the rail reads as an overshoot, not as a
    // reading of 0 or 100.
    expect(markerShift(0)).toBe(0);
    expect(markerShift(100)).toBe(-100);
  });

  it('centres the marker everywhere in between', () => {
    expect(markerShift(50)).toBe(-50);
  });
});

describe('BANDS', () => {
  it('covers 0–100 with no gap and no overlap', () => {
    expect(BANDS[0].max).toBe(29);
    expect(BANDS[BANDS.length - 1].max).toBe(100);
    for (let i = 1; i < BANDS.length; i += 1) {
      expect(BANDS[i].max).toBeGreaterThan(BANDS[i - 1].max);
    }
  });
});

describe('formatIndex', () => {
  it('writes the reading as a bare whole number', () => {
    expect(formatIndex(27)).toBe('27');
    expect(formatIndex(27.4)).toBe('27');
  });

  it('writes a missing reading as the placeholder, never as zero', () => {
    expect(formatIndex(null)).toBe(UNKNOWN);
  });
});

describe('formatProbability', () => {
  it('writes a 0–1 price as a percentage', () => {
    expect(formatProbability(0.28)).toBe('28%');
  });

  it('writes a missing price as the placeholder', () => {
    expect(formatProbability(null)).toBe(UNKNOWN);
  });
});

describe('hasReading', () => {
  it('treats only an outage as having nothing to render', () => {
    expect(hasReading('calm')).toBe(true);
    expect(hasReading('happened')).toBe(true);
    expect(hasReading('unavailable')).toBe(false);
  });
});
