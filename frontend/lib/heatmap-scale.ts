/**
 * The heatmap's colour scales — one source of truth for tiles and legend.
 *
 * These used to be two separate pieces of code: a chain of if-statements that
 * coloured a tile, and a hand-written legend beside it. They disagreed. The
 * legend claimed a neutral swatch meant "~0%" while the colour function never
 * produced that swatch for a price at all, so matching a faint red tile against
 * the legend gave no match.
 *
 * Here a scale is data. `bucketFor` walks it and the legend renders the same
 * array, which makes disagreement structurally impossible rather than merely
 * unlikely — and a test pins that they still agree.
 */

export interface HeatBucket {
  /** Inclusive lower bound. Buckets are ordered high to low. */
  min: number;
  /**
   * Tailwind classes for the tile: background, the ink that stays readable on
   * it, and any border it needs.
   *
   * Background and ink are declared together on purpose. The ramps span a real
   * lightness range — a top stop dark enough for light text would be too dark
   * to read as a tile at all — so the brightest stop flips to `text-bg`. Left
   * to the component, that flip would be a second place to keep in sync with
   * globals.css, which is exactly how the legend drifted from the tiles before.
   */
  className: string;
  /** What the legend prints beside the swatch. */
  label: string;
}

/**
 * No reading at all.
 *
 * Distinguished from a low value by texture, not just colour: a dashed outline
 * survives being printed in greyscale and being seen by someone who cannot tell
 * the darkest ramp stop from the surface behind it. Before this, "no data" and
 * "lowest bucket" were the same flat swatch, which is how the Volume tab came
 * to look broken — almost every tile rendered in the shared bucket.
 */
export const UNKNOWN_BUCKET: HeatBucket = {
  min: Number.NEGATIVE_INFINITY,
  className: 'bg-surface-2 text-fg border border-dashed border-line-strong',
  label: 'No data',
};

/**
 * Diverging: intensity tracks distance from flat, hue tracks direction.
 *
 * Both ramps are luminance-matched step for step in globals.css, so a -6% move
 * reads exactly as intense as a +6% one.
 */
export const PRICE_SCALE: readonly HeatBucket[] = [
  { min: 5, className: 'bg-heat-up-4 text-bg', label: '≥ +5%' },
  { min: 3, className: 'bg-heat-up-3 text-fg', label: '+3 … +5%' },
  { min: 1, className: 'bg-heat-up-2 text-fg', label: '+1 … +3%' },
  { min: 0, className: 'bg-heat-up-1 text-fg', label: '0 … +1%' },
  { min: -1, className: 'bg-heat-down-1 text-fg', label: '-1 … 0%' },
  { min: -3, className: 'bg-heat-down-2 text-fg', label: '-3 … -1%' },
  { min: -5, className: 'bg-heat-down-3 text-fg', label: '-5 … -3%' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-down-4 text-bg', label: '≤ -5%' },
] as const;

/**
 * Sequential: a volume score has magnitude but no direction.
 *
 * The bounds are the score's own log anchors, so the labels can name real
 * dollar figures instead of an opaque 0-100 number. See `_volume_score` in
 * backend/services/heatmap_service.py.
 */
export const VOLUME_SCALE: readonly HeatBucket[] = [
  { min: 80, className: 'bg-heat-seq-4 text-bg', label: '≥ $10B' },
  { min: 60, className: 'bg-heat-seq-3 text-fg', label: '≥ $1B' },
  { min: 40, className: 'bg-heat-seq-2 text-fg', label: '≥ $100M' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-seq-1 text-fg', label: '< $100M' },
] as const;

/**
 * Turnover: a few percent of market cap a day is ordinary, double digits means
 * the asset is being churned unusually hard.
 */
export const TURNOVER_SCALE: readonly HeatBucket[] = [
  { min: 20, className: 'bg-heat-seq-4 text-bg', label: '≥ 20%' },
  { min: 10, className: 'bg-heat-seq-3 text-fg', label: '10 … 20%' },
  { min: 5, className: 'bg-heat-seq-2 text-fg', label: '5 … 10%' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-seq-1 text-fg', label: '< 5%' },
] as const;

/** Generic 0-100 score. */
export const SCORE_SCALE: readonly HeatBucket[] = [
  { min: 75, className: 'bg-heat-seq-4 text-bg', label: '75 … 100' },
  { min: 50, className: 'bg-heat-seq-3 text-fg', label: '50 … 75' },
  { min: 25, className: 'bg-heat-seq-2 text-fg', label: '25 … 50' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-seq-1 text-fg', label: '0 … 25' },
] as const;

/**
 * The bucket a value falls in, or {@link UNKNOWN_BUCKET} when there is none.
 *
 * Every scale ends at -Infinity, so a real number always matches something and
 * the unknown state is reachable only by actually being unknown.
 */
export function bucketFor(value: number | undefined, scale: readonly HeatBucket[]): HeatBucket {
  if (value === undefined || !Number.isFinite(value)) return UNKNOWN_BUCKET;
  return scale.find((bucket) => value >= bucket.min) ?? UNKNOWN_BUCKET;
}
