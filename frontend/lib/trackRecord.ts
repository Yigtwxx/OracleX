/**
 * Reading the track record.
 *
 * The backend decides what may be claimed — it withholds a hit rate below the
 * sample floor, keeps neutral verdicts out of the directional figure, and
 * computes the benchmark on the same denominator as the rate. This module only
 * renders those decisions, and its one job is to never undo them.
 *
 * That is why the derivations are here rather than inside the component. A rate
 * printed over four samples, or an edge computed against a null benchmark, is a
 * plausible number on a page about accuracy — the most expensive kind of silent
 * failure this codebase has, and the reason the vitest suite is concentrated on
 * pure logic in the first place.
 */

/** A bucket the backend scored. `hitRate` is null when it refused to state one. */
export interface HorizonBucket {
  readonly horizon_days: number;
  readonly n: number;
  readonly hits: number;
  readonly hit_rate: number | null;
  /** What the best fixed answer scored on exactly these calls. */
  readonly baseline_rate?: number | null;
  readonly baseline_direction?: string | null;
}

export interface ObservedBucket {
  readonly horizon_days: number;
  readonly n: number;
  readonly bullish: number;
  readonly bearish: number;
  readonly neutral: number;
}

export interface LabelledBucket extends Omit<HorizonBucket, 'horizon_days'> {
  readonly horizon_days?: number;
  readonly materiality?: string;
  readonly band?: string;
  readonly from?: number;
  readonly to?: number;
}

export interface TrackRecordSummary {
  readonly generated_at: string;
  readonly min_samples: number;
  readonly horizons: readonly number[];
  readonly totals: {
    readonly predictions: number;
    readonly predictions_scored: number;
    readonly measured: number;
    readonly unmeasurable: number;
    readonly pending: number;
  };
  readonly directional: {
    readonly overall: HorizonBucket | Omit<HorizonBucket, 'horizon_days'>;
    readonly by_horizon: readonly HorizonBucket[];
  };
  readonly neutral: { readonly by_horizon: readonly HorizonBucket[] };
  readonly observed: readonly ObservedBucket[];
  readonly by_materiality: readonly LabelledBucket[];
  readonly by_confidence: readonly LabelledBucket[];
  readonly excluded: {
    readonly keyword_fallback_predictions: number;
    readonly keyword_fallback_measurements: number;
  };
  readonly pipeline_versions: readonly string[];
}

/** Why a bucket shows no rate — the three states are rendered differently. */
export type BucketState = 'reported' | 'too-few' | 'unscored';

export function bucketState(bucket: Pick<HorizonBucket, 'n' | 'hit_rate'>): BucketState {
  if (bucket.n === 0) return 'unscored';
  return bucket.hit_rate === null ? 'too-few' : 'reported';
}

/**
 * A rate as a percentage, or an em dash.
 *
 * Null is the backend saying "not enough to state", and it has to survive to
 * the screen as an absence. Rendering `0%` for it would turn a refusal into the
 * worst possible claim.
 */
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return '—';
  return `${Math.round(rate * 100)}%`;
}

/** A signed percentage-point move, for a price change. */
export function formatPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return '—';
  const rounded = Math.round(pct * 10) / 10;
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}%`;
}

/** Horizons read as durations, not as raw day counts, past a month. */
export function horizonLabel(days: number): string {
  if (days >= 365) return `${Math.round(days / 365)}y`;
  if (days >= 30) return `${Math.round(days / 30)}mo`;
  return `${days}d`;
}

/**
 * How far the model beat the best fixed answer, in percentage points.
 *
 * Null whenever either side is null — never with the missing half read as zero.
 * A benchmark the backend declined to state is not a benchmark of zero, and
 * treating it as one would report the entire hit rate as edge.
 */
export function edgePoints(
  bucket: Pick<HorizonBucket, 'hit_rate' | 'baseline_rate'>
): number | null {
  const { hit_rate: rate, baseline_rate: baseline } = bucket;
  if (rate === null || rate === undefined) return null;
  if (baseline === null || baseline === undefined) return null;
  return Math.round((rate - baseline) * 1000) / 10;
}

export function formatEdge(points: number | null): string {
  if (points === null) return '—';
  const rounded = Math.round(points * 10) / 10;
  if (rounded === 0) return 'level';
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded).toFixed(1)} pts`;
}

/**
 * The share of the market's own direction at one horizon.
 *
 * Returned as fractions of the measured rows so the caller can render a mix
 * without dividing by a count it might read from a different bucket.
 */
export function observedMix(
  bucket: ObservedBucket
): { bullish: number; bearish: number; neutral: number } | null {
  if (!bucket.n) return null;
  return {
    bullish: bucket.bullish / bucket.n,
    bearish: bucket.bearish / bucket.n,
    neutral: bucket.neutral / bucket.n,
  };
}

/**
 * What fraction of the calls that could have been scored have been.
 *
 * `pending` is the honest part: horizons that have come due and carry no
 * measurement yet. A page that showed only what resolved would be reporting a
 * different and much kinder record.
 */
export function coverage(totals: TrackRecordSummary['totals']): number | null {
  const closed = totals.measured + totals.unmeasurable;
  const total = closed + totals.pending;
  return total ? closed / total : null;
}

/** True when nothing has been scored yet, so the page leads with why. */
export function isEmpty(summary: TrackRecordSummary | undefined): boolean {
  if (!summary) return true;
  return summary.totals.measured === 0;
}
