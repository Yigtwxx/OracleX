/**
 * Derivations for the open-interest board.
 *
 * The payload carries three arrays aligned index-for-index with the candles,
 * and every pane below the first two is a transform of them. Those transforms
 * live here rather than inside the chart component for one reason: a `null` in
 * these arrays means "this venue did not report that bar", and the difference
 * between propagating that hole and quietly treating it as a zero is the
 * difference between an honest chart and a plausible wrong one. That decision
 * deserves tests, and a `useMemo` cannot have them.
 */

/**
 * Period-over-period change in the aggregate, as a percentage.
 *
 * `null` wherever either end of the comparison is missing, and wherever the
 * earlier value is zero — a percentage change from nothing is not infinity, it
 * is undefined, and drawing it as a bar would put a spike on the chart at the
 * exact moment the data is weakest.
 */
export function aggregateChangePct(aggregate: (number | null)[], lookback = 1): (number | null)[] {
  return aggregate.map((value, index) => {
    const previous = aggregate[index - lookback];
    if (value == null || previous == null || previous === 0) return null;
    return ((value - previous) / previous) * 100;
  });
}

/**
 * Aggregate open interest as a share of market cap, as a percentage.
 *
 * How much leverage the asset is carrying relative to its own size — the number
 * that says whether a given open-interest figure is large or merely nominal.
 * `market_cap` arrives empty when circulating supply is unknown, which is a
 * missing pane rather than a zero ratio.
 */
export function oiToMarketCapRatio(
  aggregate: (number | null)[],
  marketCap: number[]
): (number | null)[] {
  if (marketCap.length === 0) return aggregate.map(() => null);
  return aggregate.map((value, index) => {
    const cap = marketCap[index];
    if (value == null || cap == null || cap === 0) return null;
    return (value / cap) * 100;
  });
}

/** One venue's share of the aggregate at a bar, as a percentage. */
export interface VenueShare {
  venue: string;
  value: number;
  share: number;
}

/**
 * Each venue's open interest at `index`, with its share of that bar's total.
 *
 * Shares are computed against the venues that actually reported, not against
 * the full venue list — a bar where one exchange is missing still adds to 100%,
 * because the alternative is a tooltip whose numbers do not sum and which gives
 * the reader no way to tell why.
 */
export function venueShare(
  series: Record<string, (number | null)[]>,
  venues: string[],
  index: number
): VenueShare[] {
  const present = venues
    .map((venue) => ({ venue, value: series[venue]?.[index] }))
    .filter((entry): entry is { venue: string; value: number } => entry.value != null);

  const total = present.reduce((sum, entry) => sum + entry.value, 0);
  return present.map(({ venue, value }) => ({
    venue,
    value,
    share: total > 0 ? (value / total) * 100 : 0,
  }));
}

export interface WindowSummary {
  /** Newest reported value in the window, or null when nothing reported. */
  latest: number | null;
  /** Oldest reported value in the window. */
  first: number | null;
  /** Change from `first` to `latest`, as a percentage. */
  changePct: number | null;
}

/**
 * The headline figure and its change across whatever is currently in view.
 *
 * Reads from the first and last *reported* bars rather than the first and last
 * slots: a window that opens on a gap would otherwise report no change at all,
 * which is the one answer that is certainly wrong.
 */
export function windowSummary(aggregate: (number | null)[]): WindowSummary {
  const reported = aggregate.filter((value): value is number => value != null);
  if (reported.length === 0) return { latest: null, first: null, changePct: null };

  const first = reported[0];
  const latest = reported[reported.length - 1];
  return {
    latest,
    first,
    changePct: first === 0 ? null : ((latest - first) / first) * 100,
  };
}

/** `#rrggbb` plus an alpha, as the `rgba()` string ECharts wants. */
export function withAlpha(hex: string, alpha: number): string {
  const clean = hex.trim().replace('#', '');
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((c) => c + c)
          .join('')
      : clean;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  if ([r, g, b].some(Number.isNaN)) return hex;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
