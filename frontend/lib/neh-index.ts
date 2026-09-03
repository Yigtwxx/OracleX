import type { NehIndexStatus } from '@/lib/api';

/**
 * Presentation rules for the Nothing Ever Happens Index.
 *
 * Kept beside `pizza-index.ts` and shaped the same way, because the two gauges
 * share one panel and a reader comparing them should not have to learn two
 * visual languages. What differs is the scale: this one is a probability in
 * percent, so it gets a filled track, while the pizza reading is a multiple of
 * normal and gets a centred dial.
 */

/** Shown wherever a reading could not be taken. Never a 0 — see `formatIndex`. */
export const UNKNOWN = '—';

/**
 * The bands, upper bound inclusive, mirroring `BANDS` in
 * `services/neh_index_service.py`. Two constants in two languages: if the
 * server's edges move, this is the line that has to move with them.
 */
export const BANDS: { max: number; status: NehIndexStatus; label: string }[] = [
  { max: 29, status: 'calm', label: 'Nothing Ever Happens' },
  { max: 64, status: 'watch', label: 'Something Might Happen' },
  { max: 98, status: 'happening', label: 'Something Is Happening' },
  { max: 100, status: 'happened', label: 'It Happened' },
];

/**
 * Where a reading sits on the track, as a 0–100 percentage of its width.
 *
 * Each band owns a quarter of the track regardless of how many points it spans,
 * because the bands are what the track is for. Drawn to scale, "It Happened"
 * would be a two-point sliver nobody could see the marker enter, and the 69
 * points of "Nothing Ever Happens" would swallow two thirds of the width for
 * the one state in which the gauge has nothing to say.
 *
 * Returns null for a missing reading so the caller renders an empty track
 * rather than parking the marker at zero, which would look like a measured calm.
 */
export function bandPosition(index: number | null): number | null {
  if (index === null) return null;
  const value = Math.max(0, Math.min(100, index));

  let floor = 0;
  for (let i = 0; i < BANDS.length; i += 1) {
    const { max } = BANDS[i];
    if (value <= max) {
      const span = max - floor;
      const within = span === 0 ? 1 : (value - floor) / span;
      return (i + within) * 25;
    }
    floor = max + 1;
  }
  return 100;
}

/**
 * How much of the track is filled, given a marker position.
 *
 * Split out from the position itself because the two answer different
 * questions and the strip got them confused: lighting a whole band the moment
 * the marker touched its left edge drew a gauge that ran a full quarter of the
 * track past its own marker. A reading of 30 — the first point of "Something
 * Might Happen" — filled halfway while the marker stood at a quarter.
 *
 * `band` is the segment the marker is standing in and `within` is how far into
 * it, as a percentage of that one segment, so a caller can fill the segments
 * before it outright and stop the last one exactly under the marker.
 *
 * `band` is -1 for a missing reading, which leaves the whole track unlit.
 */
export function trackFill(position: number | null): { band: number; within: number } {
  if (position === null) return { band: -1, within: 0 };

  const clamped = Math.max(0, Math.min(100, position));
  const width = 100 / BANDS.length;
  // Not `Math.floor` alone: a position of exactly 100 lands one band past the
  // end, and the reading that matters most is the one that would fall off.
  const band = Math.min(BANDS.length - 1, Math.floor(clamped / width));
  return { band, within: ((clamped - band * width) / width) * 100 };
}

/**
 * How far to pull the marker back along its own width, as a percentage.
 *
 * A marker centred with a flat -50% hangs half outside the rail at 0 and at
 * 100, which reads as a gauge that overshot rather than one pinned to its end.
 * Interpolating the pull-back with the position instead keeps every reading
 * inside the track: flush left at 0, centred in the middle, flush right at 100.
 * It costs under a pixel of centring error on a two-pixel marker, which is
 * cheaper than the alternative of special-casing the two ends.
 */
export function markerShift(position: number): number {
  const clamped = Math.max(0, Math.min(100, position));
  // Guarded rather than a bare negation: `-0` is what that returns at the left
  // edge, and a negative zero travelling into a transform string is a footgun
  // nobody reading `translate(-0%, -50%)` would expect to be there.
  return clamped === 0 ? 0 : -clamped;
}

/**
 * The reading as it is written: `27`.
 *
 * Rendered bare rather than as `27%` in the compact row, because the caption
 * beside it already says what the number is a probability of — and a percent
 * sign there reads as "the index is 27% of something", which it is not.
 */
export function formatIndex(index: number | null): string {
  if (index === null) return UNKNOWN;
  return String(Math.round(index));
}

/** A market probability as the panel writes it: `28%`. */
export function formatProbability(probability: number | null): string {
  if (probability === null) return UNKNOWN;
  return `${Math.round(probability * 100)}%`;
}

/**
 * Text colour for a status.
 *
 * `calm` is green here where the pizza gauge deliberately refuses green for its
 * quiet end — and that difference is the point. Quieter pizza is not good news,
 * it is the other direction; a low probability of a strike is unambiguously the
 * better outcome, so the up/down palette means what it says.
 */
export function statusTone(status: NehIndexStatus): string {
  switch (status) {
    case 'calm':
      return 'text-up';
    case 'watch':
      return 'text-warn';
    case 'happening':
      return 'text-[var(--pizza)]';
    case 'happened':
      return 'text-down';
    default:
      return 'text-fg-subtle';
  }
}

/** The same scale as a CSS colour, for the track fill. */
export function statusColor(status: NehIndexStatus): string {
  switch (status) {
    case 'calm':
      return 'var(--up)';
    case 'watch':
      return 'var(--warn)';
    case 'happening':
      return 'var(--pizza)';
    case 'happened':
      return 'var(--down)';
    default:
      return 'var(--fg-subtle)';
  }
}

/** True when the payload carries a number to render. */
export function hasReading(status: NehIndexStatus): boolean {
  return status !== 'unavailable';
}
