import { ANALYSIS_MARKS, Mark } from './analysis-marks';
import { CandleSeries } from './candle-series';
import { PRINT_FROM, PRINT_TO, printedFraction, progressAtVh } from './stages';

export interface ActiveMark {
  readonly mark: Mark;
  /** 0 → not drawn yet, 1 → fully drawn. */
  readonly reveal: number;
}

export interface SceneState {
  readonly progress: number;
  /**
   * Fractional. 12.4 means twelve finished candles plus one grown 40% of the
   * way. Never zero: the board carries a seeded stretch of tape before the page
   * has been scrolled at all (see `SEED_FRACTION`).
   */
  readonly printedCount: number;
  readonly gridAlpha: number;
  /** First candle index in the visible window. The pan falls out of this. */
  readonly windowFrom: number;
  readonly slots: number;
  readonly priceMin: number;
  readonly priceMax: number;
  readonly marks: readonly ActiveMark[];
}

/** Headroom above and below the visible price range. */
const DOMAIN_PADDING = 0.06;

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * The graph paper is already under the seeded tape at rest — paper without ink
 * would be the one combination that looks unfinished — and comes the rest of
 * the way up as the first new candles land.
 */
const GRID_REST = 0.55;
const GRID_TO = progressAtVh(12);

export function sceneAt(progress: number, series: CandleSeries, slots: number): SceneState {
  const p = clamp01(progress);
  const total = series.candles.length;

  const printedCount = printedFraction((p - PRINT_FROM) / (PRINT_TO - PRINT_FROM)) * total;
  const gridAlpha = GRID_REST + (1 - GRID_REST) * clamp01(p / GRID_TO);

  // Always at least one candle in the domain, or the scale is degenerate before
  // anything has printed and the first bar arrives at an arbitrary height.
  const visibleTo = Math.max(1, Math.min(Math.ceil(printedCount), total));
  const windowFrom = Math.max(0, visibleTo - slots);

  let low = Infinity;
  let high = -Infinity;
  for (let i = windowFrom; i < visibleTo; i += 1) {
    const candle = series.candles[i];
    if (candle.l < low) low = candle.l;
    if (candle.h > high) high = candle.h;
  }
  const pad = Math.max((high - low) * DOMAIN_PADDING, high * 0.001);

  return {
    progress: p,
    printedCount,
    gridAlpha,
    windowFrom,
    slots,
    priceMin: low - pad,
    priceMax: high + pad,
    // What keeps annotations off the hero is their own schedule — every mark's
    // window sits inside a feature stage. This is the floor underneath that,
    // and the one thing that still holds if the seed is ever taken back to 0.
    marks:
      printedCount <= 0
        ? []
        : ANALYSIS_MARKS.filter((m) => p >= m.from).map((m) => ({
            mark: m.mark,
            reveal: clamp01((p - m.from) / Math.max(m.to - m.from, 1e-6)),
          })),
  };
}
