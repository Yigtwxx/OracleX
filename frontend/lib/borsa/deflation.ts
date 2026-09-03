import type { BistFund } from '@/lib/bist-api';

/**
 * The page's argument, as coordinates.
 *
 * `/borsa` claims a lira gain and a purchasing-power gain are different
 * numbers. The hero makes that claim about one fund; this module makes it about
 * the board, which is the only version of the claim that is a fact about the
 * market rather than an anecdote.
 *
 * Kept out of the component because the vitest suite only collects `lib/**`
 * (`vitest.config.mts`) — a scale that silently inverts is exactly the kind of
 * failure a screenshot does not catch.
 */

/** One fund, read twice. */
export interface DeflationRow {
  code: string;
  title: string;
  /** Fraction, as the API sends it: `0.315` is +%31,5. */
  nominal: number;
  real: number;
  /** What inflation took, in return points. Always ≥ 0 for a nominal gain. */
  erosion: number;
  /** Gained in lira, lost in purchasing power — the case the page is about. */
  realLoss: boolean;
  /** Either end falls beyond the plotted domain and is drawn pinned to the edge. */
  offScale: boolean;
}

export interface DeflationScale {
  rows: readonly DeflationRow[];
  /** Compressed domain bounds; `positionOf` maps into [0, 1] against these. */
  min: number;
  max: number;
  /** Where zero sits on the axis, in [0, 1]. The rows hang off this line. */
  zero: number;
  /** Rows that were measurable but did not fit `limit`, so the cap is visible. */
  omitted: number;
  /** Rows pinned to the right edge, so the axis never lies about its own range. */
  offScale: number;
  realLosses: number;
}

/**
 * Returns on TEFAS span two orders of magnitude in a single year — the top of
 * the one-year table was +%1300 the week this was written and the tenth row was
 * +%104. On a linear axis every row below the first collapses into the same
 * pixel and the chart says only that one fund had a good year.
 *
 * A signed square root keeps the sign, keeps the order, and keeps a +%30 row
 * visibly different from a +%60 one while an outlier at +%1300 still reads as
 * far away. Log would be better at spreading the small end and cannot take the
 * negative values that are the whole point of the chart.
 */
function compress(value: number): number {
  return Math.sign(value) * Math.sqrt(Math.abs(value));
}

/**
 * The axis stops at the bulk of the data, not at its furthest point.
 *
 * One fund returned +%1300 last year and the tenth returned +%104. Scaled to
 * the outlier — even compressed — twelve of fourteen rows collapse into the
 * left third and the chart says only that one fund had an extraordinary year,
 * which is the fact the reader already had. Cutting the domain at the 85th
 * percentile of every plotted value spreads the rows that carry the argument
 * and pins the two that do not; `offScale` counts them so the chart can say
 * outright that they run past the edge rather than quietly clipping them.
 */
const DOMAIN_QUANTILE = 0.85;
const DOMAIN_HEADROOM = 1.15;

function quantile(sorted: readonly number[], q: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)));
  return sorted[index];
}

/**
 * Build the chart's rows from a fund list.
 *
 * `window` is a framed-return key (`'1y'`). A fund with no real figure for that
 * window is dropped rather than plotted at zero: the missing case here is "the
 * inflation series does not cover this period", and drawing it as no erosion
 * would make the chart argue the opposite of the page.
 */
export function buildDeflation(
  funds: readonly BistFund[],
  window: string,
  limit: number = 20
): DeflationScale {
  const measured: DeflationRow[] = [];

  for (const fund of funds) {
    const framed = fund.framed_returns?.[window];
    if (!framed || framed.real === null || !Number.isFinite(framed.nominal)) continue;
    if (!Number.isFinite(framed.real)) continue;
    measured.push({
      code: fund.code,
      title: fund.title,
      nominal: framed.nominal,
      real: framed.real,
      erosion: framed.nominal - framed.real,
      realLoss: framed.nominal > 0 && framed.real < 0,
      offScale: false,
    });
  }

  // Sorted by the claim the reader arrived with — the number every other site
  // ranks by — so the chart reorders nothing and only adds the second reading.
  measured.sort((a, b) => b.nominal - a.nominal);

  const picked = measured.slice(0, limit);
  const values = picked.flatMap((row) => [compress(row.nominal), compress(row.real)]);
  // Zero is always in the domain: the axis has to show which side of nothing a
  // fund landed on, even when every row on screen is positive.
  values.push(0);

  const ascending = [...values].sort((a, b) => a - b);
  const min = ascending[0];
  const bulk = quantile(ascending, DOMAIN_QUANTILE);
  // Headroom keeps the last in-scale row off the edge, where it would be
  // indistinguishable from a row that ran past it.
  const max = Math.max(bulk * DOMAIN_HEADROOM, min + 1e-9);
  const span = max - min || 1;

  const rows = picked.map((row) => ({
    ...row,
    offScale: compress(row.nominal) > max || compress(row.real) > max,
  }));

  return {
    rows,
    min,
    max,
    zero: (0 - min) / span,
    omitted: Math.max(0, measured.length - rows.length),
    offScale: rows.filter((row) => row.offScale).length,
    realLosses: rows.filter((row) => row.realLoss).length,
  };
}

/** Where a return sits on the axis, in [0, 1]. */
export function positionOf(scale: DeflationScale, value: number): number {
  const span = scale.max - scale.min || 1;
  const position = (compress(value) - scale.min) / span;
  return position < 0 ? 0 : position > 1 ? 1 : position;
}
