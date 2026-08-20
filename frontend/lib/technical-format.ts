import type { PriceZone, RsiRead } from '@/store/useStore';

/**
 * Formatting for the technical panel.
 *
 * One rule runs through all of it: a band is rendered as a band. The backend
 * stopped quoting support as a single decimal because a level is an area price
 * reversed in, and a display that averages the two bounds back into one number
 * puts that false precision straight back.
 */

/** Shown wherever a reading could not be taken. Never a 0. */
export const UNKNOWN = '—';

/**
 * Price at a precision that suits its magnitude.
 *
 * A chart panel mixes BTC at 64,294 with a token at 0.00031 in the same column,
 * so the decimal count comes from the number rather than from a constant.
 */
export function formatLevel(value: number): string {
  const magnitude = Math.abs(value);
  const decimals = magnitude >= 1000 ? 0 : magnitude >= 1 ? 2 : magnitude >= 0.01 ? 4 : 8;
  return `$${value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

/**
 * A zone as the band it is.
 *
 * A band whose bounds are equal came from one reversal at one price; printing
 * "$100 – $100" would suggest a width that was never measured.
 */
export function formatBand(zone: Pick<PriceZone, 'low' | 'high'>): string {
  return zone.low === zone.high
    ? formatLevel(zone.low)
    : `${formatLevel(zone.low)} – ${formatLevel(zone.high)}`;
}

/** Signed percent, so a reader never has to infer direction from colour alone. */
export function formatSignedPercent(value: number | null | undefined, decimals = 1): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return UNKNOWN;
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`;
}

/** Which timeframes found a band, as one string: "1d+1w+4h". */
export function confirmedOn(zone: PriceZone): string {
  const timeframes = zone.timeframes?.length ? zone.timeframes : [zone.timeframe];
  return timeframes.filter(Boolean).join('+') || UNKNOWN;
}

/**
 * The direction token for a trend or an RSI signal.
 *
 * Returns a semantic name rather than a class so the caller decides whether it
 * paints text, a background, or nothing — and so this stays testable.
 */
export type Tone = 'up' | 'down' | 'warn' | 'muted';

export function trendTone(trend: string | null | undefined): Tone {
  if (trend === 'bullish') return 'up';
  if (trend === 'bearish') return 'down';
  if (trend === 'neutral') return 'warn';
  return 'muted';
}

/**
 * RSI's tone is about extremes, not direction.
 *
 * Overbought is not "good" and oversold is not "bad" — both are stretched, which
 * is why they share the warning tone rather than borrowing the up/down palette
 * that means something else everywhere else in this app.
 */
export function rsiTone(rsi: RsiRead | undefined): Tone {
  const value = rsi?.value;
  if (typeof value !== 'number') return 'muted';
  if (value >= 70 || value <= 30) return 'warn';
  if (value >= 60) return 'up';
  if (value <= 40) return 'down';
  return 'muted';
}

/** Arrow for an RSI slope. Always paired with the numeric change in the UI. */
export function slopeMark(slope: string | null | undefined): string {
  if (slope === 'rising') return '↑';
  if (slope === 'falling') return '↓';
  if (slope === 'flat') return '→';
  return '';
}

/**
 * Human label for a horizon.
 *
 * The horizon comes from the longest timeframe that confirmed the band, not
 * from its distance to spot, so the label says what it is measured on.
 */
export const HORIZON_LABEL: Record<string, string> = {
  short: 'Short',
  medium: 'Medium',
  long: 'Long',
  single: 'This chart',
};

export function horizonLabel(horizon: string): string {
  return HORIZON_LABEL[horizon] ?? horizon;
}

/**
 * Where price sits between two bounds, as a 0–1 fraction, or null.
 *
 * Null rather than a midpoint when the range is unknown: a marker placed
 * anywhere on an undrawable bar reads as a measurement.
 */
export function rangeFraction(
  price: number | null | undefined,
  low: number | null | undefined,
  high: number | null | undefined
): number | null {
  if (typeof price !== 'number' || typeof low !== 'number' || typeof high !== 'number') return null;
  const span = high - low;
  if (span <= 0) return null;
  return Math.min(1, Math.max(0, (price - low) / span));
}
