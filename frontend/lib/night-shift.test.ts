import { describe, expect, it } from 'vitest';

import {
  MUKERRER_BANDS,
  formatIndex,
  markerShift,
  mukerrerColor,
  mukerrerFill,
  mukerrerPosition,
  mukerrerState,
  padHistory,
  SPARK_DAYS,
  statusCaption,
} from './night-shift';

describe('formatIndex', () => {
  it('writes the reading with the decimal comma the rest of the realm uses', () => {
    // A lone `1.4×` beside `%31,8` reads as a different product's number.
    expect(formatIndex(1.4)).toBe('1,4×');
    expect(formatIndex(0.5)).toBe('0,5×');
  });

  it('drops the decimal once the multiple is large enough not to need it', () => {
    expect(formatIndex(12.3)).toBe('12×');
  });

  it('never renders a missing reading as a zero', () => {
    expect(formatIndex(null)).toBe('—');
  });
});

describe('mukerrerPosition', () => {
  it('pins the marker to the right on the day an extra edition is published', () => {
    expect(mukerrerPosition(0)).toBe(100);
  });

  it('runs calm to happened from left to right', () => {
    // The strip beside it reads the same way; inverting one would make a reader
    // relearn the gauge when they switch realms.
    const long = mukerrerPosition(80)!;
    const medium = mukerrerPosition(20)!;
    const recent = mukerrerPosition(3)!;
    expect(long).toBeLessThan(medium);
    expect(medium).toBeLessThan(recent);
    expect(recent).toBeLessThan(100);
  });

  it('caps the scale so a long silence does not sit at the rail all year', () => {
    // Past a quarter the difference between three months and six is not a
    // reading anyone acts on.
    expect(mukerrerPosition(90)).toBe(0);
    expect(mukerrerPosition(400)).toBe(0);
  });

  it('puts the measured 56-day silence in the calm quarter', () => {
    const position = mukerrerPosition(56)!;
    expect(position).toBeGreaterThan(0);
    expect(position).toBeLessThan(25);
  });

  it('draws no marker for a figure that was never taken', () => {
    expect(mukerrerPosition(null)).toBeNull();
    expect(mukerrerPosition(Number.NaN)).toBeNull();
    expect(mukerrerPosition(-1)).toBeNull();
  });
});

describe('mukerrerState', () => {
  it('reads today as happened whichever field says so', () => {
    expect(mukerrerState(0, false)).toBe('happened');
    expect(mukerrerState(5, true)).toBe('happened');
  });

  it('bands the quiet by how long it has lasted', () => {
    expect(mukerrerState(3, false)).toBe('recent');
    expect(mukerrerState(20, false)).toBe('quiet');
    expect(mukerrerState(56, false)).toBe('calm');
  });

  it('treats no record at all as calm rather than as an event', () => {
    expect(mukerrerState(null, false)).toBe('calm');
  });
});

describe('mukerrerFill', () => {
  it('stops the lit segment under the marker rather than a quarter past it', () => {
    const position = mukerrerPosition(56)!;
    const fill = mukerrerFill(position);
    expect(fill.band).toBe(0);
    expect(fill.within).toBeGreaterThan(0);
    expect(fill.within).toBeLessThan(100);
  });

  it('keeps a reading of exactly 100 inside the last band', () => {
    // `Math.floor` alone lands one band past the end, and the reading that
    // matters most is the one that would fall off.
    expect(mukerrerFill(100).band).toBe(MUKERRER_BANDS.length - 1);
  });

  it('leaves the whole track unlit for a missing reading', () => {
    expect(mukerrerFill(null)).toEqual({ band: -1, within: 0 });
  });
});

describe('markerShift', () => {
  it('keeps the marker inside the rail at both ends', () => {
    expect(markerShift(0)).toBe(0);
    expect(markerShift(100)).toBe(-100);
    expect(markerShift(50)).toBe(-50);
  });
});

describe('mukerrerColor', () => {
  it('gives a long silence the calm end of the ramp, not the alarm end', () => {
    expect(mukerrerColor('calm')).toBe('var(--up)');
    expect(mukerrerColor('happened')).toBe('var(--down)');
  });
});

describe('statusCaption', () => {
  it('says why a refusal happened rather than leaving a blank', () => {
    expect(statusCaption('unavailable', 0)).toContain('ulaşılamadı');
    expect(statusCaption('insufficient_data', 1)).toContain('1 kaynak');
    expect(statusCaption('insufficient_data', 0)).toContain('Hiçbir kaynak');
  });
});

describe('padHistory', () => {
  const day = (d: string, ratio: number | null) => ({ day: d, ratio });

  it('puts every source on the same axis whatever its record length', () => {
    // The bug this replaced: a source with five days spread them over the width
    // the row above gives fourteen, so the two rows' columns no longer lined up.
    expect(padHistory([day('2026-08-27', 1), day('2026-08-28', 2)])).toHaveLength(SPARK_DAYS);
    expect(padHistory([])).toHaveLength(SPARK_DAYS);
  });

  it('pads on the left, so the newest day stays on the right', () => {
    const padded = padHistory([day('2026-08-28', 2)]);
    expect(padded[padded.length - 1]).toEqual(day('2026-08-28', 2));
    expect(padded[0]).toBeNull();
  });

  it('keeps an unscored day as a slot rather than closing the gap', () => {
    // A null ratio inside the record and a null slot before it mean different
    // things, and both have to draw — see the module docs.
    const padded = padHistory([day('2026-08-27', null), day('2026-08-28', 2)]);
    expect(padded[SPARK_DAYS - 2]).toEqual(day('2026-08-27', null));
  });

  it('keeps the most recent days when the record is longer than the axis', () => {
    const long = Array.from({ length: 20 }, (_, i) =>
      day(`2026-08-${String(i + 1).padStart(2, '0')}`, 1)
    );
    const padded = padHistory(long);
    expect(padded).toHaveLength(SPARK_DAYS);
    expect(padded[padded.length - 1]?.day).toBe('2026-08-20');
  });

  it('survives a source with no history at all', () => {
    expect(padHistory(null)).toEqual(Array(SPARK_DAYS).fill(null));
    expect(padHistory(undefined)).toEqual(Array(SPARK_DAYS).fill(null));
  });
});
