import { CoinData } from './api';

/**
 * Derivations that answer "how many, in which direction" about a market — the
 * question the aggregate totals in the stats bar cannot answer.
 *
 * Market cap and 24h volume describe the market's size. They say nothing about
 * participation: a +1.5% average can be four hundred assets drifting up or two
 * megacaps carrying a flat tail, and those are opposite markets. Everything
 * here is computed from the market-overview payload the page already holds, so
 * none of it costs a request.
 *
 * Pure functions on purpose. This is where a silent wrong number would do the
 * most damage — a breadth reading nobody can sanity-check against a chart — so
 * it lives in `lib/` under test rather than inside a component.
 */

// A move has to be a move. Exact zero is what an untraded or stale row reports,
// and counting those as "advancing" would inflate every reading on a quiet day.
const isAdvancing = (change: number): boolean => change > 0;
const isDeclining = (change: number): boolean => change < 0;

/** Assets whose 24h turnover is below this are excluded from divergence lists. */
export const DIVERGENCE_MIN_VOLUME = 1_000_000;

export interface BreadthSummary {
  total: number;
  advancing: number;
  declining: number;
  unchanged: number;
  /** Share of the universe that advanced, 0–100. */
  advancingPct: number;
  /** Advancing / declining. `null` when nothing declined — the ratio is undefined, not infinite. */
  advanceDeclineRatio: number | null;
  /** Same count over the weekly change, for assets that report one. */
  advancing7d: number | null;
  reporting7d: number;
  /** Typical asset. Diverges from the mean exactly when a few outliers carry the tape. */
  medianChange: number | null;
  meanChange: number | null;
  /** What an index would print — the mean weighted by market cap. */
  capWeightedChange: number | null;
  /** Median position inside the 24h low–high band, 0–1. Where the day is closing. */
  medianRangePosition: number | null;
  rangeReporting: number;
  upperHalfCount: number;
  /** Share of 24h turnover held by the ten busiest assets, 0–100. */
  top10VolumeShare: number | null;
}

const median = (values: number[]): number | null => {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
};

const mean = (values: number[]): number | null =>
  values.length === 0 ? null : values.reduce((sum, v) => sum + v, 0) / values.length;

/** Guards every field read off the payload: upstream sends nulls and NaN. */
const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export function computeBreadth(coins: CoinData[]): BreadthSummary {
  const changes = coins.map((c) => c.change_24h).filter(isNumber);

  const advancing = changes.filter(isAdvancing).length;
  const declining = changes.filter(isDeclining).length;
  const total = changes.length;

  const weekly = coins.map((c) => c.change_7d).filter(isNumber);

  // Cap weighting needs both halves of every term, so rows missing either one
  // are dropped from the numerator *and* the denominator. Dropping only the
  // numerator would silently shrink the result toward zero.
  const weighted = coins.filter(
    (c) => isNumber(c.change_24h) && isNumber(c.market_cap) && c.market_cap > 0
  );
  const totalCap = weighted.reduce((sum, c) => sum + c.market_cap, 0);
  const capWeightedChange =
    totalCap > 0
      ? weighted.reduce((sum, c) => sum + c.change_24h * c.market_cap, 0) / totalCap
      : null;

  // Where in its own day each asset is trading. A degenerate band (high <= low)
  // is what a partially-reported row looks like and carries no position.
  const positions: number[] = [];
  for (const coin of coins) {
    const { high_24h: high, low_24h: low, price } = coin;
    if (!isNumber(high) || !isNumber(low) || !isNumber(price) || high <= low) continue;
    positions.push(Math.min(1, Math.max(0, (price - low) / (high - low))));
  }

  const volumes = coins.map((c) => c.volume_24h).filter(isNumber);
  const totalVolume = volumes.reduce((sum, v) => sum + v, 0);
  const top10Volume = [...volumes]
    .sort((a, b) => b - a)
    .slice(0, 10)
    .reduce((sum, v) => sum + v, 0);

  return {
    total,
    advancing,
    declining,
    unchanged: total - advancing - declining,
    advancingPct: total > 0 ? (advancing / total) * 100 : 0,
    advanceDeclineRatio: declining > 0 ? advancing / declining : null,
    advancing7d: weekly.length > 0 ? weekly.filter(isAdvancing).length : null,
    reporting7d: weekly.length,
    medianChange: median(changes),
    meanChange: mean(changes),
    capWeightedChange,
    medianRangePosition: median(positions),
    rangeReporting: positions.length,
    upperHalfCount: positions.filter((p) => p > 0.5).length,
    top10VolumeShare: totalVolume > 0 ? (top10Volume / totalVolume) * 100 : null,
  };
}

// ---------------------------------------------------------------------------
// Distribution
// ---------------------------------------------------------------------------

export interface HistogramBucket {
  /** Inclusive lower bound, percent. `-Infinity` on the leftmost bucket. */
  min: number;
  /** Exclusive upper bound, percent. `Infinity` on the rightmost. */
  max: number;
  label: string;
  count: number;
}

/**
 * Fixed edges, deliberately. Trimming empty end buckets would make the axis
 * rescale on every refresh, and a chart whose axis moves cannot be compared to
 * the one you looked at a minute ago. Empty tails are information: the day the
 * `<-20%` column fills is the day worth noticing.
 */
const BUCKET_EDGES = [-20, -10, -6, -3, -1, 0, 1, 3, 6, 10, 20];

// The space after the comparison operator is load-bearing: the UI renders these
// in a mono face with ligatures on, where "<-20%" is drawn as a left arrow.
const bucketLabel = (min: number, max: number): string => {
  const sign = (v: number) => (v > 0 ? `+${v}` : `${v}`);
  if (min === -Infinity) return `< ${max}%`;
  if (max === Infinity) return `> ${sign(min)}%`;
  return `${sign(min)} / ${sign(max)}`;
};

export function changeHistogram(coins: CoinData[]): HistogramBucket[] {
  const bounds = [-Infinity, ...BUCKET_EDGES, Infinity];
  const buckets: HistogramBucket[] = [];
  for (let i = 0; i < bounds.length - 1; i += 1) {
    buckets.push({
      min: bounds[i],
      max: bounds[i + 1],
      label: bucketLabel(bounds[i], bounds[i + 1]),
      count: 0,
    });
  }

  for (const coin of coins) {
    if (!isNumber(coin.change_24h)) continue;
    // Half-open [min, max) throughout, so a value landing exactly on an edge
    // is counted once and always on the same side.
    const index = buckets.findIndex((b) => coin.change_24h >= b.min && coin.change_24h < b.max);
    if (index >= 0) buckets[index].count += 1;
  }

  return buckets;
}

/** Whether an asset's 24h change falls in a bucket — the table's filter predicate. */
export const inBucket = (coin: CoinData, bucket: Pick<HistogramBucket, 'min' | 'max'>): boolean =>
  isNumber(coin.change_24h) && coin.change_24h >= bucket.min && coin.change_24h < bucket.max;

// ---------------------------------------------------------------------------
// Divergence
// ---------------------------------------------------------------------------

export interface Divergences {
  /** Up today, down on the week — attempting a turn. */
  reversing: CoinData[];
  /** Down today, up on the week — giving back the run. */
  fading: CoinData[];
}

/**
 * Assets whose day contradicts their week. The volume floor is not optional:
 * the tail of a 250-asset list is where the largest percentage moves live and
 * where none of them can be acted on, so an unfiltered board is a list of
 * names nobody can trade.
 */
export function findDivergences(
  coins: CoinData[],
  { minVolume = DIVERGENCE_MIN_VOLUME, limit = 5 }: { minVolume?: number; limit?: number } = {}
): Divergences {
  const liquid = coins.filter(
    (c) =>
      isNumber(c.change_24h) &&
      isNumber(c.change_7d) &&
      isNumber(c.volume_24h) &&
      c.volume_24h >= minVolume
  );

  return {
    reversing: liquid
      .filter((c) => c.change_24h > 0 && (c.change_7d as number) < 0)
      .sort((a, b) => b.change_24h - a.change_24h)
      .slice(0, limit),
    fading: liquid
      .filter((c) => c.change_24h < 0 && (c.change_7d as number) > 0)
      .sort((a, b) => a.change_24h - b.change_24h)
      .slice(0, limit),
  };
}
