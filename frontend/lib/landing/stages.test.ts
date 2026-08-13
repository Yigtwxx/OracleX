import { describe, expect, it } from 'vitest';
import {
  PRINT_FROM,
  PRINT_TO,
  progressAtVh,
  progressOfCandle,
  STAGE_WINDOWS,
  STAGES,
  TRACK_VH,
  windowFor,
  within,
} from './stages';

describe('STAGE_WINDOWS', () => {
  it('has one window per stage, in order', () => {
    expect(STAGE_WINDOWS.map((w) => w.key)).toEqual(STAGES.map((s) => s.key));
  });

  it('starts at exactly 0 — the hero owns the top of the page', () => {
    expect(STAGE_WINDOWS[0].from).toBe(0);
  });

  it('ends at exactly 1', () => {
    expect(STAGE_WINDOWS[STAGE_WINDOWS.length - 1].to).toBe(1);
  });

  it('is monotonic and non-overlapping, covering [0, 1] with no gaps', () => {
    STAGE_WINDOWS.forEach((w, i) => {
      expect(w.to, `stage ${w.key}`).toBeGreaterThan(w.from);
      if (i > 0) expect(w.from).toBeCloseTo(STAGE_WINDOWS[i - 1].to, 12);
    });
  });

  it('derives from the stage heights', () => {
    expect(TRACK_VH).toBe(STAGES.reduce((sum, s) => sum + s.vh, 0));
  });
});

describe('progressOfCandle', () => {
  it('spans the print window from the end of the seed to the last candle', () => {
    // The head of the series is on the board before the page moves, so it has
    // no print progress to report. Everything after it spans the window.
    expect(progressOfCandle(0, 100)).toBe(0);
    expect(progressOfCandle(99, 100)).toBeCloseTo(PRINT_TO, 12);
  });

  it('never goes backwards, and is strictly increasing past the seed', () => {
    for (let i = 1; i < 100; i += 1) {
      const previous = progressOfCandle(i - 1, 100);
      const current = progressOfCandle(i, 100);
      expect(current, `candle ${i}`).toBeGreaterThanOrEqual(previous);
      if (previous > 0) expect(current, `candle ${i}`).toBeGreaterThan(previous);
    }
  });

  it('answers the first scroll gesture instead of waiting for the hero to clear', () => {
    // Not zero — at rest the board shows the seeded tape and nothing newer —
    // but well inside the first flick of the wheel, and long before the `print`
    // section arrives.
    expect(PRINT_FROM).toBeGreaterThan(0);
    expect(PRINT_FROM).toBeLessThan(windowFor('print').from);
    expect(PRINT_FROM).toBeCloseTo(progressAtVh(10), 12);
  });
});

describe('progressAtVh', () => {
  it('maps scroll distance onto the track, clamped at both ends', () => {
    expect(progressAtVh(0)).toBe(0);
    expect(progressAtVh(-50)).toBe(0);
    expect(progressAtVh(TRACK_VH)).toBe(1);
    expect(progressAtVh((TRACK_VH - 100) / 2)).toBeCloseTo(0.5, 12);
  });
});

describe('within', () => {
  it('carves a sub-window out of a stage', () => {
    const stage = windowFor('live');
    const slot = within('live', 0.25, 0.75);
    expect(slot.from).toBeCloseTo(stage.from + (stage.to - stage.from) * 0.25, 12);
    expect(slot.to).toBeCloseTo(stage.from + (stage.to - stage.from) * 0.75, 12);
  });
});

describe('windowFor', () => {
  it('throws on an unknown stage rather than returning a silent default', () => {
    // @ts-expect-error — deliberately outside StageKey
    expect(() => windowFor('nope')).toThrow();
  });
});
