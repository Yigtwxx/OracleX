import type { BistFundsQuery } from '@/lib/bist-api';

/**
 * The one fund request the marketing page makes.
 *
 * Four blocks on `/borsa` need the TEFAS one-year table — the hero's worked
 * example, the deflation chart, the top-ten table and the coverage line — and
 * three of them used to ask for it separately with different limits, which is
 * three round trips for one answer. React Query dedupes on the key, so sharing
 * the literal is what makes them one.
 *
 * Forty rather than ten: the chart needs enough measurable rows to read as a
 * market, and `real_loss` is computed server-side across every fund regardless
 * of what this asks for, so the limit only bounds the rows drawn.
 */
export const BOARD_FUNDS: BistFundsQuery = { sort_by: '1y', limit: 40 };

/** The window every framed return on this page is read in. */
export const BOARD_WINDOW = '1y';
