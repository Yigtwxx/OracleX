import { mulberry32 } from './prng';

export interface Candle {
  readonly o: number;
  readonly h: number;
  readonly l: number;
  readonly c: number;
  readonly v: number;
}

export interface CandleSeries {
  readonly candles: readonly Candle[];
  readonly maxVolume: number;
}

/**
 * One phase of the story the tape tells. Hand-authored rather than sampled,
 * because a random walk does not look like a market — it has no accumulation,
 * no impulse, no capitulation, and a viewer who trades reads that as noise
 * within about two seconds. The PRNG only fills in texture inside a regime; the
 * shape of the story is a decision.
 */
interface Regime {
  readonly bars: number;
  /** Mean log-ish return per bar. */
  readonly drift: number;
  /** Half-width of the per-bar shock, as a fraction of price. */
  readonly vol: number;
  /** -1 pushes wicks below the body, +1 above, 0 is symmetric. */
  readonly wickBias: number;
  readonly volume: number;
}

const REGIMES: readonly Regime[] = [
  // Accumulation — tight, low volume, going nowhere. The chart needs somewhere
  // boring to start or the breakout has nothing to break out of.
  { bars: 26, drift: 0.0005, vol: 0.009, wickBias: 0, volume: 0.65 },
  // Breakout impulse.
  { bars: 22, drift: 0.011, vol: 0.012, wickBias: 0.25, volume: 1.5 },
  // Pullback into the breakout level.
  { bars: 12, drift: -0.006, vol: 0.011, wickBias: -0.3, volume: 0.9 },
  // Markup.
  { bars: 24, drift: 0.009, vol: 0.013, wickBias: 0.15, volume: 1.25 },
  // Blow-off top — long upper wicks, heaviest volume of the series.
  { bars: 10, drift: 0.016, vol: 0.022, wickBias: 0.8, volume: 2.0 },
  // Distribution — flat, still busy. This is where the supply zone gets drawn.
  { bars: 16, drift: -0.001, vol: 0.014, wickBias: 0.3, volume: 1.1 },
  // Capitulation — the long lower wicks the liquidity-sweep marks point at.
  { bars: 12, drift: -0.019, vol: 0.024, wickBias: -0.9, volume: 2.2 },
  // Recovery. Ends the page on a rising trendline rather than a drawdown.
  { bars: 26, drift: 0.0065, vol: 0.013, wickBias: -0.15, volume: 1.0 },
];

const START_PRICE = 43_120;
const BASE_VOLUME = 1_000;

/** Total bar count, derived so callers never restate it. */
export const CANDLE_COUNT = REGIMES.reduce((sum, r) => sum + r.bars, 0);

/**
 * Index boundaries of each regime, for scheduling annotations against the story
 * rather than against magic numbers. `REGIME_BOUNDS[2]` is the pullback.
 */
export const REGIME_BOUNDS: readonly { readonly start: number; readonly end: number }[] = (() => {
  const bounds: { start: number; end: number }[] = [];
  let cursor = 0;
  for (const regime of REGIMES) {
    bounds.push({ start: cursor, end: cursor + regime.bars - 1 });
    cursor += regime.bars;
  }
  return bounds;
})();

export function buildSeries(seed: number): CandleSeries {
  const rand = mulberry32(seed);
  const candles: Candle[] = [];
  let price = START_PRICE;
  let maxVolume = 0;

  for (const regime of REGIMES) {
    for (let i = 0; i < regime.bars; i += 1) {
      const o = price;
      const shock = (rand() * 2 - 1) * regime.vol;
      const c = Math.max(o * (1 + regime.drift + shock), 1);

      const bodyTop = Math.max(o, c);
      const bodyBottom = Math.min(o, c);
      // Wick length scales with the regime's volatility and is skewed by its
      // bias, so a blow-off tops out with spikes and a capitulation bottoms out
      // with tails without either needing a special case.
      const upBias = 1 + regime.wickBias;
      const downBias = 1 - regime.wickBias;
      const h = bodyTop * (1 + rand() * regime.vol * 0.9 * Math.max(upBias, 0.05));
      const l = bodyBottom * (1 - rand() * regime.vol * 0.9 * Math.max(downBias, 0.05));

      // Wide bars trade more. Without this the histogram is flat noise and the
      // impulse reads exactly like the chop.
      const bodyRatio = Math.abs(c - o) / o / Math.max(regime.vol, 1e-6);
      const v = BASE_VOLUME * regime.volume * (0.55 + rand() * 0.7 + bodyRatio * 0.5);

      candles.push({ o, h, l, c, v });
      if (v > maxVolume) maxVolume = v;
      price = c;
    }
  }

  return { candles, maxVolume };
}

/** Built once at module load. Identical on the server and in every browser. */
export const BTC_SERIES: CandleSeries = buildSeries(20240117);
