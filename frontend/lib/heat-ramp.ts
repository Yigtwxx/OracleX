/**
 * The colour ramp a density heatmap reads through.
 *
 * Liquidity is extremely skewed — a handful of magnet levels dwarf everything
 * else — so two corrections do the work that a plain linear ramp cannot:
 *
 * **Gamma before the lookup.** Without it every cell but the top few collapses
 * into the darkest stop and the map reads as empty.
 *
 * **Hue and opacity pulled apart.** Hue climbs quickly so the mid range
 * separates; alpha climbs on a steep curve so weak cells sink into the
 * background instead of washing the whole canvas one colour. Only the real
 * magnets reach full opacity.
 *
 * Extracted from `components/charts/LiquidationHeatmap.tsx`, which still holds
 * its own copy along with six selectable schemes and their persistence. That
 * chart is working and out of scope here; collapsing it onto this module is a
 * separate change worth making the next time it is touched.
 */

import { parseHex } from '@/lib/chart-palette';

/** Gamma applied to `value / ceiling` before the ramp lookup. */
export const HEAT_GAMMA = 0.5;

/** Exponent on the opacity ramp; > 1 keeps faint cells close to the background. */
export const HEAT_ALPHA_CURVE = 2.1;

/** Percentile of cell values treated as full heat; anything above it saturates. */
export const HEAT_INTENSITY_CLIP = 0.98;

/**
 * `steps` colours from the given stops, alpha rising on its own curve.
 */
export function buildRamp(stops: string[], steps = 96): string[] {
  const parsed = stops.map(parseHex);

  return Array.from({ length: steps }, (_, index) => {
    const t = index / (steps - 1);
    const scaled = t * (parsed.length - 1);
    const lower = Math.min(Math.floor(scaled), parsed.length - 2);
    const local = scaled - lower;

    const [r, g, b] = parsed[lower].map((channel, axis) =>
      Math.round(channel + (parsed[lower + 1][axis] - channel) * local)
    );
    const alpha = 0.03 + 0.97 * Math.pow(t, HEAT_ALPHA_CURVE);
    return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
  });
}

/**
 * The value treated as full heat.
 *
 * A high percentile rather than the outright maximum: one untouched level far
 * from price can sit an order of magnitude above everything else, and scaling
 * to it flattens the whole map into a single shade. Clipping instead lets the
 * handful of genuine magnets saturate.
 */
export function heatCeiling(values: number[]): number {
  if (values.length === 0) return 1;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * HEAT_INTENSITY_CLIP)] || 1;
}

/** Index into a ramp for one value, gamma-corrected against `ceiling`. */
export function rampIndex(value: number, ceiling: number, rampLength: number): number {
  const intensity = Math.pow(Math.min(value / ceiling, 1), HEAT_GAMMA);
  return Math.round(intensity * (rampLength - 1));
}
