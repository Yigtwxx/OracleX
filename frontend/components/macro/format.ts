/**
 * Shared formatting for the macro board.
 *
 * The board mixes scales that differ by four orders of magnitude — natural gas
 * at 2.64, the Nikkei at 65,606 — so a single decimal count would either round
 * gas to "3" or pad the index with meaningless zeros. Everything here picks its
 * precision from the magnitude of the number it is given.
 */

/** Shown wherever a reading could not be taken. Never a 0. */
export const UNKNOWN = '—';

/** Price with a decimal count that suits its magnitude. */
export function formatPrice(value: number): string {
  const magnitude = Math.abs(value);
  const decimals = magnitude >= 1000 ? 2 : magnitude >= 10 ? 2 : magnitude >= 1 ? 3 : 4;
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Ratio value at the precision the server said it is meaningful to. */
export function formatRatio(value: number, decimals: number): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Where `price` sits between the 52-week low and high, as a 0–1 fraction.
 *
 * `null` when either bound is missing or the range has collapsed — a bar drawn
 * from an unknown range would put the marker somewhere arbitrary and read as a
 * measurement.
 */
export function rangePosition(
  price: number | null,
  low: number | null,
  high: number | null
): number | null {
  if (price === null || low === null || high === null) return null;
  const span = high - low;
  if (span <= 0) return null;
  // A futures contract can print outside its own trailing 52-week range; clamp
  // so the marker stays on the bar instead of sliding past its ends.
  return Math.min(1, Math.max(0, (price - low) / span));
}
