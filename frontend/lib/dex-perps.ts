import type { DexPerpVenue } from './api';
import { parseHex } from './chart-palette';

/**
 * How many venues a panel draws.
 *
 * The cut is here rather than on the backend so changing it needs no deploy,
 * and the panel header reports the full count beside it — a truncated ranking
 * that does not say it is truncated reads as a complete one.
 */
export const TOP_N = 15;

/** The leaders of an already-ranked panel, in the order the backend sent. */
export function topVenues(rows: DexPerpVenue[], n: number = TOP_N): DexPerpVenue[] {
  return rows.slice(0, n);
}

/**
 * Each row's share of the rows passed in — not of the panel.
 *
 * Called with a top-N slice it answers "share of the leaders", which is the
 * only share the chart can honestly label, since the tail is off-screen.
 */
export function shareOfTotal(rows: DexPerpVenue[]): number[] {
  const total = rows.reduce((sum, row) => sum + row.value_usd, 0);
  if (total <= 0) return rows.map(() => 0);
  return rows.map((row) => row.value_usd / total);
}

/**
 * A positive lower bound for a log axis.
 *
 * Log scales are undefined at zero, and ECharts left to itself picks a floor
 * that makes the smallest bar vanish. Half the smallest value keeps every bar
 * visible without inventing headroom the data does not have.
 */
export function logFloor(rows: DexPerpVenue[]): number {
  const values = rows.map((row) => row.value_usd).filter((value) => value > 0);
  if (values.length === 0) return 1;
  return Math.min(...values) / 2;
}

/**
 * One colour per bar, interpolated across the tokens a panel is given.
 *
 * Fifteen ranked bars want fifteen distinguishable colours, and fifteen
 * unrelated hues would be a rainbow that encodes nothing — the venue is already
 * named on the axis and marked by its logo at the bar's tip. Walking one ramp
 * instead means the colour carries the ranking: the leader and the tail are
 * visibly far apart, and the three panels stay recognisably one board.
 *
 * Returns `rgb()` strings because ECharts hands colours straight to the canvas
 * context, which cannot resolve a CSS custom property.
 */
export function rampColors(count: number, stops: readonly string[]): string[] {
  if (count <= 0) return [];

  const usable = stops.filter((stop) => /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(stop));
  if (usable.length === 0) return [];
  const rgb = usable.map(parseHex);
  const format = ([r, g, b]: [number, number, number]) => `rgb(${r}, ${g}, ${b})`;
  // One stop, or one bar to paint: there is nothing to interpolate between.
  if (rgb.length === 1 || count === 1) return Array.from({ length: count }, () => format(rgb[0]));

  const lastStop = rgb.length - 1;

  return Array.from({ length: count }, (_, i) => {
    const position = (i / (count - 1)) * lastStop;
    // Clamped so the final bar reads from the last pair rather than running one
    // stop past the end of the array.
    const lower = Math.min(Math.floor(position), lastStop - 1);
    const t = position - lower;
    const from = rgb[lower];
    const to = rgb[lower + 1];
    const channel = (a: number, b: number) => Math.round(a + (b - a) * t);
    return format([channel(from[0], to[0]), channel(from[1], to[1]), channel(from[2], to[2])]);
  });
}
