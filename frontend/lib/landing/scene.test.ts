import { describe, expect, it } from 'vitest';
import { BTC_SERIES, CANDLE_COUNT } from './candle-series';
import { sceneAt } from './scene';
import { PRINT_FROM, progressAtVh, windowFor } from './stages';

const SLOTS = 72;
const scene = (p: number) => sceneAt(p, BTC_SERIES, SLOTS);

describe('sceneAt', () => {
  it('opens on a board that is already running', () => {
    // An empty board is a large dark rectangle across the bottom half of the
    // first screen. The seeded tape is what fills it, and it has to be there
    // before the page is scrolled at all — not a few vh in.
    const state = scene(0);
    expect(state.printedCount).toBeGreaterThan(CANDLE_COUNT * 0.3);
    expect(state.gridAlpha).toBeGreaterThan(0.4);
    expect(state.marks).toEqual([]);
  });

  it('leaves the head of the tape room to grow into', () => {
    // The other half of the seed: scrolling has to be visibly doing something.
    // A board that is already full can only pan.
    expect(scene(0).printedCount).toBeLessThan(CANDLE_COUNT * 0.45);
  });

  it('keeps the hero clear of annotations even with the tape running', () => {
    for (const p of [0, PRINT_FROM * 0.5, PRINT_FROM]) {
      expect(scene(p).marks, `at ${p}`).toEqual([]);
    }
  });

  it('adds to the tape within the first flick of the wheel', () => {
    // Candles arrive a few vh in, not half a screen down. A regression here
    // makes the page feel dead on load.
    expect(scene(progressAtVh(14)).printedCount).toBeGreaterThan(scene(0).printedCount);
    expect(progressAtVh(14)).toBeLessThan(windowFor('print').from);
  });

  it('brings the grid the rest of the way up as the first candles land', () => {
    expect(scene(0).gridAlpha).toBeLessThan(1);
    expect(scene(progressAtVh(4)).gridAlpha).toBeGreaterThan(scene(0).gridAlpha);
    expect(scene(progressAtVh(12)).gridAlpha).toBeCloseTo(1, 10);
  });

  it('prints monotonically and finishes the series', () => {
    let previous = -1;
    for (let i = 0; i <= 200; i += 1) {
      const state = scene(i / 200);
      expect(state.printedCount).toBeGreaterThanOrEqual(previous);
      previous = state.printedCount;
    }
    expect(scene(1).printedCount).toBeCloseTo(CANDLE_COUNT, 6);
  });

  it('keeps the price domain finite and non-degenerate at every position', () => {
    for (let i = 0; i <= 200; i += 1) {
      const state = scene(i / 200);
      expect(Number.isFinite(state.priceMin), `min at ${i}`).toBe(true);
      expect(Number.isFinite(state.priceMax), `max at ${i}`).toBe(true);
      expect(state.priceMax, `span at ${i}`).toBeGreaterThan(state.priceMin);
    }
  });

  it('pans only once the window is full', () => {
    expect(scene(PRINT_FROM + 0.01).windowFrom).toBe(0);
    expect(scene(1).windowFrom).toBe(CANDLE_COUNT - SLOTS);
  });

  it('reveals marks between 0 and 1, never beyond', () => {
    for (let i = 0; i <= 200; i += 1) {
      for (const { reveal } of scene(i / 200).marks) {
        expect(reveal).toBeGreaterThanOrEqual(0);
        expect(reveal).toBeLessThanOrEqual(1);
      }
    }
  });

  it('clamps out-of-range progress rather than extrapolating', () => {
    expect(scene(-1).printedCount).toBe(scene(0).printedCount);
    expect(scene(2).printedCount).toBeCloseTo(CANDLE_COUNT, 6);
  });
});
