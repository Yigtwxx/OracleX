import type { NightShiftDay, NightShiftStatus } from '@/lib/bist-api';

/**
 * Presentation rules for the Gece Mesaisi Endeksi.
 *
 * Deliberately the Turkish twin of `lib/pizza-index.ts`, down to the dial
 * geometry and the thresholds. The two gauges sit in the same slot in the same
 * header on two different realms, and a reader who has learned that a marker
 * left of centre means "quieter than usual" on one must not have to relearn it
 * on the other.
 *
 * Kept out of the component for the same reason the pizza rules are: two copies
 * of these thresholds would drift, and the first symptom would be the same
 * reading rendering as "Normal" in the badge and "Normalin üstünde" in the
 * panel behind it.
 */

/** Shown wherever a reading could not be taken. Never a 0 — see `formatIndex`. */
export const UNKNOWN = '—';

/**
 * The server clamps ratios here, so the scale ends here too.
 *
 * Mirrors `RATIO_CAP` in `services/bist/night_shift_service.py`. Two constants
 * in two languages: if the server's cap moves, this is the line that has to
 * move with it.
 */
export const RATIO_CAP = 4;

/**
 * Where a ratio sits on the dial, as -1…+1 with 1.0× at dead centre.
 *
 * Logarithmic, because the quantity is a ratio: half as much legislation and
 * twice as much are the same size of departure from normal and belong the same
 * distance from the middle.
 *
 * Null for a missing reading, so callers render the empty state rather than
 * parking the marker at centre — which would look like a measured "normal".
 */
export function dialPosition(index: number | null): number | null {
  if (index === null || index <= 0) return null;
  const span = Math.log(RATIO_CAP);
  return Math.max(-1, Math.min(1, Math.log(index) / span));
}

/**
 * The reading as it is written: `1,4×`.
 *
 * Turkish decimal comma, because every other figure on this realm uses one and
 * a lone `1.4×` beside `%31,8` reads as a different product's number. Never
 * rescaled to 0–100: this is a multiple of usual, not a sentiment score.
 */
export function formatIndex(index: number | null): string {
  if (index === null) return UNKNOWN;
  const digits = index >= 10 ? 0 : 1;
  return `${index.toFixed(digits).replace('.', ',')}×`;
}

/**
 * Text colour for a status.
 *
 * `quiet` is deliberately not green. A quieter-than-usual week in the Resmî
 * Gazete is not a good outcome, it is simply the other direction, and the
 * up/down palette this app uses for prices would import a judgement the index
 * does not make.
 */
export function statusTone(status: NightShiftStatus): string {
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
export function statusColor(status: NightShiftStatus): string {
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
 * Bar fill for a single ratio, for the day charts.
 *
 * Thresholds are the server's own (`THRESHOLD_ELEVATED`, `THRESHOLD_SPIKE`), so
 * a bar and the headline reading of the same day can never wear different
 * colours.
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
 * different things — too few sources scored, versus the sources could not be
 * read — so components branch on `status`, not on `index === null`.
 */
export function hasReading(status: NightShiftStatus): boolean {
  return status !== 'insufficient_data' && status !== 'unavailable';
}

/** The one-line explanation under the reading. */
export function statusCaption(status: NightShiftStatus, sourcesUsed: number): string {
  switch (status) {
    case 'insufficient_data':
      return sourcesUsed > 0
        ? `Yalnız ${sourcesUsed} kaynak ölçülebildi — endeks için yetersiz`
        : 'Hiçbir kaynak ölçülemedi';
    case 'unavailable':
      return 'Kaynaklara ulaşılamadı';
    default:
      return `${sourcesUsed} kaynağın kendi olağanına göre medyanı`;
  }
}

/**
 * How long since the Resmî Gazete last published an extra edition.
 *
 * Spelled out rather than left as a number: "56" beside a date means nothing
 * without the unit, and this is the one figure on the panel a reader is most
 * likely to quote at someone else.
 */
export function mukerrerCaption(days: number | null, today: boolean): string {
  if (today) return 'Bugün mükerrer sayı yayımlandı';
  if (days === null) return 'Mükerrer kaydı yok';
  if (days === 1) return 'Son mükerrer sayı dün';
  return `Son mükerrer sayı ${days} gün önce`;
}

// ── Mükerrer sessizliği ─────────────────────────────────────────────────────

export type MukerrerState = 'calm' | 'quiet' | 'recent' | 'happened';

/**
 * How long the Resmî Gazete has gone without an extra edition, in bands.
 *
 * The Turkish counterpart to the Nothing Ever Happens strip, and the same joke:
 * measured over the 150 days to 28 August 2026 the Gazette published three
 * extra editions, so the marker sits in `calm` almost always and the gauge's
 * ordinary state is having nothing to report. That is the reading, not a
 * failure of it.
 *
 * Left to right runs calm → happened, matching the strip it sits beside: a
 * reader who has learned that a marker on the right means "it happened" on one
 * realm must not find it inverted on the other.
 *
 * Each band owns a quarter of the track regardless of how many days it spans,
 * for the reason `lib/neh-index.ts` gives: drawn to scale, `happened` would be
 * a single-day sliver nobody could see the marker enter.
 */
export const MUKERRER_BANDS: { key: MukerrerState; label: string }[] = [
  { key: 'calm', label: 'Aylardır sessiz' },
  { key: 'quiet', label: 'Sakin' },
  { key: 'recent', label: 'Bu hafta çıktı' },
  { key: 'happened', label: 'Bugün mükerrer çıktı' },
];

/**
 * Where a quiet spell of `days` sits on the track, 0–100.
 *
 * Capped at ninety days: past a quarter without an extra edition the difference
 * between three months and six is not a reading anyone acts on, and letting the
 * scale run on would park the marker at the rail for most of the year.
 *
 * Null for a missing figure, so the caller draws an empty track rather than a
 * marker at zero — which here would claim a measured three-month calm.
 */
export function mukerrerPosition(days: number | null): number | null {
  if (days === null || !Number.isFinite(days) || days < 0) return null;

  // [band index, the day count that starts the band, the day count that ends it]
  const edges: [number, number, number][] = [
    [0, 90, 31],
    [1, 30, 8],
    [2, 7, 1],
  ];

  if (days === 0) return 100;
  for (const [band, from, to] of edges) {
    if (days >= to) {
      // `from` is the band's calm edge and `to` its loud one, so the fraction
      // already grows as the silence shortens; inverting it here as well put
      // the ninety-day cap a full quarter along the track instead of at zero.
      const span = from - to;
      const within = span === 0 ? 1 : Math.min(1, Math.max(0, (from - days) / span));
      return (band + within) * 25;
    }
  }
  return 0;
}

/** The band a quiet spell falls in, for its label and colour. */
export function mukerrerState(days: number | null, today: boolean): MukerrerState {
  if (today || days === 0) return 'happened';
  if (days === null) return 'calm';
  if (days <= 7) return 'recent';
  if (days <= 30) return 'quiet';
  return 'calm';
}

/**
 * How much of the track is lit, given a marker position.
 *
 * Mirrors `trackFill` in `lib/neh-index.ts` exactly, including why it exists:
 * lighting a whole band the moment the marker touches its left edge draws a
 * gauge that runs a quarter of the track past its own marker.
 */
export function mukerrerFill(position: number | null): { band: number; within: number } {
  if (position === null) return { band: -1, within: 0 };
  const clamped = Math.max(0, Math.min(100, position));
  const width = 100 / MUKERRER_BANDS.length;
  const band = Math.min(MUKERRER_BANDS.length - 1, Math.floor(clamped / width));
  return { band, within: ((clamped - band * width) / width) * 100 };
}

/** Colour for a band, matching the index's own ramp. */
export function mukerrerColor(state: MukerrerState): string {
  switch (state) {
    case 'happened':
      return 'var(--down)';
    case 'recent':
      return 'var(--warn)';
    case 'quiet':
      return 'var(--fg)';
    default:
      return 'var(--up)';
  }
}

/**
 * How far to pull the marker back along its own width, as a percentage.
 *
 * A marker centred with a flat -50% hangs half outside the rail at 0 and at
 * 100, which reads as a gauge that overshot rather than one pinned to its end.
 */
export function markerShift(position: number): number {
  const clamped = Math.max(0, Math.min(100, position));
  // `-0` is what negating a clamped zero yields, and it is not `0` to anything
  // that compares with `Object.is` — including a test asserting the left rail.
  return clamped === 0 ? 0 : -clamped;
}

/**
 * How many days every sparkline in the panel is drawn across.
 *
 * Fixed rather than taken from the data, because the rows are read against each
 * other. A source the server has only five days of history for would otherwise
 * spread those five over the same width the others give fourteen, and the
 * fourth block of one row would sit above the eleventh block of the next.
 */
export const SPARK_DAYS = 14;

/**
 * One source's history on the shared axis: newest last, left-padded to length.
 *
 * `null` is a slot before this source's record begins; a `NightShiftDay` whose
 * `ratio` is null is a day inside it that could not be scored. Both draw as an
 * empty slot and neither is dropped — a source whose whole fortnight went
 * unscored still gets its grid, because a row with no grid at all reads as a
 * rendering fault rather than as an absence of readings.
 */
export function padHistory(
  history: NightShiftDay[] | null | undefined,
  days: number = SPARK_DAYS
): (NightShiftDay | null)[] {
  const recent = (history ?? []).slice(-days);
  return [...Array(Math.max(days - recent.length, 0)).fill(null), ...recent];
}
