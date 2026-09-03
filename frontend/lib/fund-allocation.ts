/**
 * Colour and order for the fund allocation bar.
 *
 * The grouping itself is the backend's — `services/bist/fund_allocation.py`
 * decides that a gold participation account is gold rather than a deposit.
 * What is decided here is only what a reader sees: which colour a bucket wears
 * and where in the bar it sits.
 *
 * **The colour is fixed per bucket, not resolved per bar.** This is the one
 * thing that separates this module from `components/ownership/format.ts`, whose
 * `allocationColors` picks colours against the other segments in the same bar.
 * That is right for holdings, which are arbitrary and unbounded per entity. It
 * would be wrong here: with a per-bar rotation, one fund's second segment and
 * another fund's second segment take the same colour while meaning different
 * things, and reading two rows of the screener against each other — the entire
 * reason the column exists — stops working.
 *
 * The order is fixed for the same reason, and it doubles as the adjacency plan:
 * because the sequence cannot change, the pairs that can ever touch cannot
 * either. Gold (`--data-gold`) and amber (`--chart-3`) are the only two fills
 * close in hue, and they sit six positions apart.
 *
 * The one pairing worth designing around is `hisse` beside `fon`. Those are the
 * two commonest lines TEFAS reports — 975 and 1,197 funds of 2,029 — so they
 * end up adjacent on most bars on the board, whatever the order says. `fon`
 * therefore takes terracotta rather than the violet that reads as a shade of
 * the equity indigo beside it, and violet goes to the rare property bucket.
 */

import type { FundAllocationWeights } from '@/lib/bist-api';
import { formatPercent } from '@/lib/bist-format';

/**
 * Bar order. Mirrors `BUCKET_ORDER` in `services/bist/fund_allocation.py`; the
 * server already sends buckets in it, and this is what keeps a row honest if a
 * response ever arrives in another order.
 */
export const FUND_BUCKET_ORDER = [
  'hisse',
  'yabanci_hisse',
  'gayrimenkul',
  'fon',
  'kiymetli_maden',
  'ozel_borclanma',
  'kamu_borclanma',
  'yabanci_borclanma',
  'mevduat',
  'para_piyasasi',
  'turev',
  'diger',
] as const;

/** The bucket an unmapped key falls back to, matching the backend's. */
export const UNKNOWN_BUCKET = 'diger';

/**
 * Hue names the asset family, lightness the sub-kind — so a 96px bar reads as
 * about six families at a glance and the detail legend disambiguates.
 *
 * The dim siblings mix toward `--surface-2` rather than toward `transparent`.
 * The bar's own track is `--surface-2`, so the two look identical today, but
 * only by accident: a transparent segment would shift the moment the bar sat
 * over anything else, and it would stop working entirely in the light theme.
 *
 * Nothing here is green, red, or `--warn`. A green segment on a fund's bar
 * would be read as performance. Precious metals take the app-wide gold token
 * for the same reason bitcoin is bitcoin orange everywhere: the hue names the
 * instrument, so a gold fund is recognisable across the whole board.
 */
export const FUND_BUCKET_COLOR: Record<string, string> = {
  hisse: 'var(--chart-1)',
  yabanci_hisse: 'color-mix(in srgb, var(--chart-1) 55%, var(--surface-2))',
  gayrimenkul: 'var(--chart-7)',
  fon: 'var(--chart-4)',
  kiymetli_maden: 'var(--data-gold)',
  ozel_borclanma: 'var(--chart-2)',
  kamu_borclanma: 'var(--chart-5)',
  yabanci_borclanma: 'color-mix(in srgb, var(--chart-5) 45%, var(--surface-2))',
  mevduat: 'var(--chart-6)',
  para_piyasasi: 'color-mix(in srgb, var(--chart-6) 55%, var(--surface-2))',
  turev: 'var(--chart-3)',
  diger: 'var(--fg-subtle)',
};

export interface FundAllocationSegment {
  key: string;
  label: string;
  /** Fraction of the portfolio. */
  weight: number;
  color: string;
}

export function bucketColor(key: string): string {
  return FUND_BUCKET_COLOR[key] ?? FUND_BUCKET_COLOR[UNKNOWN_BUCKET];
}

/**
 * The bar's segments, in bar order.
 *
 * `labels` is the vocabulary the board sends once in its meta block. A bucket
 * the server added and this file has not heard of keeps that server label and
 * takes the "Diğer" colour rather than being dropped — a bar that silently
 * shrinks when the backend gains a bucket would be worse than an odd colour.
 */
export function allocationSegments(
  allocation: FundAllocationWeights | null | undefined,
  labels: Record<string, string> = {}
): FundAllocationSegment[] {
  if (!allocation) return [];

  const known = FUND_BUCKET_ORDER.filter((key) => key in allocation);
  const unknown = Object.keys(allocation).filter(
    (key) => !(FUND_BUCKET_ORDER as readonly string[]).includes(key)
  );

  return [...known, ...unknown]
    .map((key) => ({
      key,
      label: labels[key] ?? key,
      weight: allocation[key],
      color: bucketColor(key),
    }))
    .filter((segment) => Number.isFinite(segment.weight) && segment.weight > 0);
}

/**
 * What TEFAS reported, summed. Never clamped to 1 — the shortfall is a fact
 * about the filing and the bar leaves it as bare track.
 */
export function allocationTotal(allocation: FundAllocationWeights | null | undefined): number {
  if (!allocation) return 0;
  return Object.values(allocation).reduce(
    (sum, weight) => (Number.isFinite(weight) && weight > 0 ? sum + weight : sum),
    0
  );
}

/**
 * The scalar the screener column sorts on: how much of the fund is equity.
 *
 * A stacked bar has no natural ordering, and "how much of this is stocks" is
 * the risk axis a screener reader is already on — it sorts the board from money
 * market to pure equity in one click. Null only when nothing was reported: a
 * fund that reported and holds no equity is a 0, and the two must not tie.
 */
export function equityWeight(allocation: FundAllocationWeights | null | undefined): number | null {
  if (!allocation) return null;
  return (allocation.hisse ?? 0) + (allocation.yabanci_hisse ?? 0);
}

/** The largest bucket, for a one-glance label. Null when nothing was reported. */
export function dominantBucket(segments: FundAllocationSegment[]): FundAllocationSegment | null {
  if (segments.length === 0) return null;
  // Ties resolve to the earlier segment, which is bar order — stable, and the
  // same answer for two funds holding the same halves.
  return segments.reduce((best, segment) => (segment.weight > best.weight ? segment : best));
}

/**
 * A bucket's weight, printed.
 *
 * The floor is the point. The bar already refuses to let a 0.03% line vanish,
 * and printing it as "%0,0" beside the segment would undo that in words: a
 * reader would take it for a holding of nothing, which is exactly the claim the
 * 2px minimum exists to avoid making.
 */
export function formatWeight(weight: number): string {
  if (weight > 0 && weight < 0.0005) return '<%0,1';
  return formatPercent(weight);
}

/**
 * The bar's tooltip: "Hisse senedi %53,2 · Fon katılma payları %32,0 · …".
 *
 * A stacked bar is unreadable to a screen reader and imprecise to a mouse, so
 * the same sentence serves as both the `title` and the `aria-label`.
 */
export function allocationSummary(segments: FundAllocationSegment[]): string {
  return segments.map((segment) => `${segment.label} ${formatWeight(segment.weight)}`).join(' · ');
}
