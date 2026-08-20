import type { PizzaIndexStatus } from '@/lib/api';

/**
 * Presentation rules for the Pentagon Pizza Index.
 *
 * Kept out of the components because the panel on Macro and the compact gauge on
 * Overview and Home have to agree on what "1.4" looks like and what colour it
 * wears. Two copies of these thresholds would drift, and the first symptom would
 * be the same reading rendering as "Normal" in one place and "Above normal" in
 * another.
 */

/** Shown wherever a reading could not be taken. Never a 0 — see `formatIndex`. */
export const UNKNOWN = '—';

/**
 * The server clamps ratios here, so the scale ends here too.
 *
 * Mirrors `RATIO_CAP` in `services/pentagon_pizza_service.py`. The two are
 * separate constants in separate languages; if the server's cap changes, this
 * is the line that has to change with it.
 */
export const RATIO_CAP = 4;

/**
 * Where a ratio sits on the dial, as -1…+1 with 1.0× at dead centre.
 *
 * Logarithmic, because the quantity is a ratio: half as busy and twice as busy
 * are the same size of departure from normal and belong the same distance from
 * the middle. On a linear scale 0.5× would sit a sixth of the way out while 2×
 * sat a third, which would read as "quiet is a smaller deviation than busy" —
 * a claim about the world rather than about the arithmetic.
 *
 * Returns null for a missing reading so callers render the empty state rather
 * than parking the marker at centre, which would look like a measured "normal".
 */
export function dialPosition(index: number | null): number | null {
  if (index === null || index <= 0) return null;
  const span = Math.log(RATIO_CAP);
  return Math.max(-1, Math.min(1, Math.log(index) / span));
}

/**
 * The reading as it is written: `1.4×`.
 *
 * Never rescaled to 0–100. This gauge sits beside Fear & Greed, and a bare
 * number on the same scale would read as the same kind of measurement — a
 * sentiment score rather than "this many times the usual busyness".
 */
export function formatIndex(index: number | null): string {
  if (index === null) return UNKNOWN;
  return `${index.toFixed(index >= 10 ? 0 : 1)}×`;
}

/** The reading as a percentage of usual, for the longer-form panel copy. */
export function formatAsPercent(index: number | null): string {
  if (index === null) return UNKNOWN;
  return `${Math.round(index * 100)}%`;
}

/**
 * Text colour for a status.
 *
 * `quiet` is deliberately not green. Quieter-than-usual is not a good outcome
 * here, it is simply the other direction, and the up/down palette this app uses
 * for prices would import a judgement the index does not make.
 */
export function statusTone(status: PizzaIndexStatus): string {
  switch (status) {
    case 'spike':
      return 'text-down';
    case 'elevated':
      return 'text-warn';
    case 'normal':
      return 'text-fg';
    case 'quiet':
      return 'text-fg-muted';
    default:
      return 'text-fg-subtle';
  }
}

/** Marker fill for the dial, as a CSS colour rather than a class. */
export function statusColor(status: PizzaIndexStatus): string {
  switch (status) {
    case 'spike':
      return 'var(--down)';
    case 'elevated':
      return 'var(--warn)';
    case 'normal':
      return 'var(--fg)';
    case 'quiet':
      return 'var(--fg-muted)';
    default:
      return 'var(--fg-subtle)';
  }
}

/**
 * Bar fill for a single ratio, for the 24h charts.
 *
 * Thresholds are the server's own (`THRESHOLD_ELEVATED`, `THRESHOLD_SPIKE`), so
 * a bar and the headline reading of the same hour can never wear different
 * colours. Kept as a ratio-keyed function rather than reusing `statusColor`,
 * because a history bar has a value but no status attached to it.
 */
export function ratioColor(ratio: number): string {
  if (ratio >= 2) return 'var(--down)';
  if (ratio >= 1.3) return 'var(--warn)';
  return 'var(--fg-muted)';
}

/**
 * True when the payload carries a number to render.
 *
 * `insufficient_data` and `unavailable` both arrive with a null index but mean
 * different things to a reader — the venues were shut, versus we could not see
 * them — so the components branch on `status`, not on `index === null`.
 */
export function hasReading(status: PizzaIndexStatus): boolean {
  return status !== 'insufficient_data' && status !== 'unavailable';
}

/** The one-line explanation under the reading. */
export function statusCaption(status: PizzaIndexStatus, venuesUsed: number): string {
  switch (status) {
    case 'insufficient_data':
      return venuesUsed > 0
        ? `Only ${venuesUsed} venue${venuesUsed === 1 ? '' : 's'} reporting — too few to score`
        : 'The venues are closed or not reporting';
    case 'unavailable':
      return 'The source could not be reached';
    default:
      return `Median of ${venuesUsed} venue${venuesUsed === 1 ? '' : 's'} against their usual hour`;
  }
}
