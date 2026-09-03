/**
 * The derivations the Konumlanma panels share.
 *
 * Four panels read the same hundred-odd rows and ask four different questions of
 * them. Putting the arithmetic here rather than in each panel is what keeps the
 * KPI strip and the charts from disagreeing: the "23 crowded names" in the strip
 * and the points inside the scatter's threshold lines are the same predicate
 * evaluated once, not two similar filters written a fortnight apart.
 *
 * It also puts the logic where the test runner can see it. `vitest.config.mts`
 * only collects `lib/**\/*.test.ts`, so a rule that lives in a component is a
 * rule nothing checks.
 *
 * Every ratio here is a fraction, not a percentage — `0.05` is five percent.
 * That is the convention the `/api/bist/*` payload converts at its boundary and
 * `bist-format` formats from.
 */

import type { BistPositioningRow } from './bist-api';

/**
 * Mirrored from `backend/services/bist/positioning_service.py`.
 *
 * Duplicated deliberately rather than shipped down in the payload: the numbers
 * are drawn on the crowding scatter as threshold lines, so the frontend needs
 * them as values and not just as a reason some rows arrived with a null score.
 * If the service moves them, the lines move here too — the test asserts the
 * scatter's own scoring agrees with the `crowding` the backend sent.
 */
export const MIN_FREE_FLOAT = 0.05;
export const MIN_RELATIVE_VOLUME = 1.0;

/** How far into its 52-week range a name has to be to count as near an extreme. */
export const NEAR_EXTREME = 0.1;

export const RANGE_BUCKETS = 20;

// ── Futures quadrants ──────────────────────────────────────────────────────

/**
 * The standard futures positioning read: what open interest did, against what
 * price did.
 *
 * Open interest is the number of contracts outstanding, so a rise means
 * positions were *opened* and a fall means they were closed. Pairing that with
 * the price direction names who was doing it — new money going long looks
 * nothing like shorts being squeezed out, and both show up as "open interest
 * moved" in a single column.
 */
export type Quadrant = 'long_build' | 'short_build' | 'short_cover' | 'long_liquidation';

export const QUADRANTS: readonly Quadrant[] = [
  'long_build',
  'short_build',
  'short_cover',
  'long_liquidation',
];

export const QUADRANT_LABEL: Record<Quadrant, string> = {
  long_build: 'Uzun kurulum',
  short_build: 'Kısa kurulum',
  short_cover: 'Kısa kapanışı',
  long_liquidation: 'Uzun tasfiyesi',
};

export const QUADRANT_NOTE: Record<Quadrant, string> = {
  long_build: 'Açık pozisyon ve fiyat birlikte arttı — yeni para uzun tarafta.',
  short_build: 'Açık pozisyon arttı, fiyat düştü — yeni para kısa tarafta.',
  short_cover: 'Açık pozisyon azaldı, fiyat arttı — kısalar kapatıyor.',
  long_liquidation: 'Açık pozisyon ve fiyat birlikte azaldı — uzunlar çıkıyor.',
};

/**
 * Which quadrant a name sits in, or null if it sits on an axis.
 *
 * Exactly zero on either axis is not a weak version of one of the four reads —
 * it is the absence of one. A contract whose open interest did not move says
 * nothing about who opened what, and rounding it into the nearest quadrant
 * would invent a direction the market did not express.
 */
export function quadrantOf(row: BistPositioningRow): Quadrant | null {
  const oi = row.open_interest_change;
  const price = row.change_pct;
  if (oi === null || price === null || oi === 0 || price === 0) return null;
  if (oi > 0) return price > 0 ? 'long_build' : 'short_build';
  return price > 0 ? 'short_cover' : 'long_liquidation';
}

// ── Cross-filter ───────────────────────────────────────────────────────────

export interface PositioningFilter {
  sector?: string;
  quadrant?: Quadrant;
  /** Index into `rangeHistogram`'s buckets. */
  rangeBucket?: number;
}

export function isFilterActive(filter: PositioningFilter): boolean {
  return (
    filter.sector !== undefined || filter.quadrant !== undefined || filter.rangeBucket !== undefined
  );
}

/** Which histogram bucket a range position falls in, or null if unmeasured. */
export function rangeBucketOf(
  position: number | null,
  buckets: number = RANGE_BUCKETS
): number | null {
  if (position === null || !Number.isFinite(position)) return null;
  const clamped = Math.min(1, Math.max(0, position));
  // The name sitting exactly at its 52-week high belongs in the last bucket,
  // not in a phantom bucket past the end.
  return Math.min(buckets - 1, Math.floor(clamped * buckets));
}

/**
 * The rows a filter selects.
 *
 * Every clause is an AND, and an unset clause selects everything — so the empty
 * filter is the whole board rather than nothing. A row that cannot answer a
 * clause (no sector, no quadrant, no measured range) is excluded by that clause
 * rather than admitted: "show me the long-build names" should not hand back the
 * names with no futures at all.
 */
export function applyFilter(
  rows: BistPositioningRow[],
  filter: PositioningFilter,
  buckets: number = RANGE_BUCKETS
): BistPositioningRow[] {
  if (!isFilterActive(filter)) return rows;
  return rows.filter((row) => {
    if (filter.sector !== undefined && row.sector !== filter.sector) return false;
    if (filter.quadrant !== undefined && quadrantOf(row) !== filter.quadrant) return false;
    if (
      filter.rangeBucket !== undefined &&
      rangeBucketOf(row.range_position, buckets) !== filter.rangeBucket
    ) {
      return false;
    }
    return true;
  });
}

// ── Summary ────────────────────────────────────────────────────────────────

export interface PositioningSummary {
  /** Names with a measurable crowding score. */
  scored: number;
  nearHigh: number;
  nearLow: number;
  /** Net open-interest growth across every name with futures, as a fraction. */
  openInterestGrowth: number | null;
  /** The quadrant holding the most names, or null on a tie or an empty board. */
  dominantQuadrant: Quadrant | null;
}

export function summarise(
  rows: BistPositioningRow[],
  futures: BistPositioningRow[]
): PositioningSummary {
  let scored = 0;
  let nearHigh = 0;
  let nearLow = 0;
  for (const row of rows) {
    if (row.crowding !== null) scored += 1;
    if (row.range_position === null) continue;
    if (row.range_position >= 1 - NEAR_EXTREME) nearHigh += 1;
    else if (row.range_position <= NEAR_EXTREME) nearLow += 1;
  }

  let openInterest = 0;
  let openInterestChange = 0;
  const perQuadrant = new Map<Quadrant, number>();
  for (const row of futures) {
    if (row.open_interest !== null) openInterest += row.open_interest;
    if (row.open_interest_change !== null) openInterestChange += row.open_interest_change;
    const quadrant = quadrantOf(row);
    if (quadrant) perQuadrant.set(quadrant, (perQuadrant.get(quadrant) ?? 0) + 1);
  }

  // Growth against yesterday's book, which is today's minus what it changed by.
  // Dividing by today's total instead would understate a build and overstate a
  // liquidation, because the denominator would already contain the move.
  const previous = openInterest - openInterestChange;
  const openInterestGrowth = previous > 0 ? openInterestChange / previous : null;

  return {
    scored,
    nearHigh,
    nearLow,
    openInterestGrowth,
    dominantQuadrant: argmax(perQuadrant),
  };
}

/** The key with the strictly highest count, or null when nothing wins outright. */
function argmax(counts: Map<Quadrant, number>): Quadrant | null {
  let best: Quadrant | null = null;
  let bestCount = 0;
  let tied = false;
  for (const [key, count] of Array.from(counts.entries())) {
    if (count > bestCount) {
      best = key;
      bestCount = count;
      tied = false;
    } else if (count === bestCount) {
      tied = true;
    }
  }
  return tied ? null : best;
}

// ── Range distribution ─────────────────────────────────────────────────────

export interface RangeBucket {
  index: number;
  /** Fractional bounds, `from` inclusive and `to` exclusive except at 1.0. */
  from: number;
  to: number;
  count: number;
  /** Median RSI of the names in this bucket, or null if none published one. */
  medianRsi: number | null;
}

/**
 * Where the board sits between its own 52-week extremes.
 *
 * Colouring each bucket by its median RSI is the point of carrying RSI at all:
 * a tall bucket near the high whose RSI has fallen back is a market that has
 * stopped being bought while still being expensive, and neither number alone
 * says that.
 */
export function rangeHistogram(
  rows: BistPositioningRow[],
  buckets: number = RANGE_BUCKETS
): RangeBucket[] {
  const rsiByBucket: number[][] = Array.from({ length: buckets }, () => []);
  const counts = new Array<number>(buckets).fill(0);

  for (const row of rows) {
    const index = rangeBucketOf(row.range_position, buckets);
    if (index === null) continue;
    counts[index] += 1;
    if (row.rsi !== null) rsiByBucket[index].push(row.rsi);
  }

  return counts.map((count, index) => ({
    index,
    from: index / buckets,
    to: (index + 1) / buckets,
    count,
    medianRsi: median(rsiByBucket[index]),
  }));
}

// ── Sector heat ────────────────────────────────────────────────────────────

export interface SectorAggregate {
  sector: string;
  /** Summed crowding — the treemap's area channel. */
  crowding: number;
  medianRelativeVolume: number | null;
  count: number;
}

/**
 * Crowding gathered by sector, heaviest first.
 *
 * Only scored rows contribute. A sector whose names all failed the float or
 * volume floors has no crowding to show, and giving it a tile sized by its
 * market capitalisation instead would put the largest quiet sector at the
 * centre of a map about unusual activity.
 */
export function sectorAggregates(rows: BistPositioningRow[]): SectorAggregate[] {
  const crowding = new Map<string, number>();
  const volumes = new Map<string, number[]>();
  const counts = new Map<string, number>();

  for (const row of rows) {
    if (row.crowding === null) continue;
    const sector = row.sector || 'Diğer';
    crowding.set(sector, (crowding.get(sector) ?? 0) + row.crowding);
    counts.set(sector, (counts.get(sector) ?? 0) + 1);
    if (row.relative_volume !== null) {
      const bucket = volumes.get(sector);
      if (bucket) bucket.push(row.relative_volume);
      else volumes.set(sector, [row.relative_volume]);
    }
  }

  return Array.from(crowding.entries())
    .map(([sector, total]) => ({
      sector,
      crowding: total,
      medianRelativeVolume: median(volumes.get(sector) ?? []),
      count: counts.get(sector) ?? 0,
    }))
    .sort((a, b) => b.crowding - a.crowding);
}

// ── Scatter inputs ─────────────────────────────────────────────────────────

export interface CrowdingPoint {
  ticker: string;
  sector: string;
  freeFloat: number;
  relativeVolume: number;
  marketCap: number | null;
  changePct: number | null;
  crowding: number | null;
}

/**
 * The crowding scatter's points.
 *
 * A row missing either axis is dropped rather than pinned to zero: the x axis
 * is logarithmic and a zero free float has no position on it, and an invented
 * one would land in the very corner the panel exists to draw attention to.
 */
export function crowdingPoints(rows: BistPositioningRow[]): CrowdingPoint[] {
  const points: CrowdingPoint[] = [];
  for (const row of rows) {
    if (row.free_float_pct === null || row.free_float_pct <= 0) continue;
    if (row.relative_volume === null || row.relative_volume <= 0) continue;
    points.push({
      ticker: row.ticker,
      sector: row.sector,
      freeFloat: row.free_float_pct,
      relativeVolume: row.relative_volume,
      marketCap: row.market_cap,
      changePct: row.change_pct,
      crowding: row.crowding,
    });
  }
  return points;
}

export interface FuturesPoint {
  ticker: string;
  sector: string;
  openInterest: number;
  openInterestChange: number;
  /**
   * The same change against yesterday's book, as a fraction.
   *
   * This, not the raw contract count, is what the quadrant chart plots. Two
   * underlyings' contract counts are not comparable — SASA carries fourteen
   * million and Akbank one — so on an absolute axis the largest book alone sets
   * the scale and every other name collapses onto the origin. "Open interest
   * grew a seventh" is both comparable across names and the thing a reader
   * means when they say a position was built.
   *
   * Null when yesterday's book was empty, which would make the growth infinite
   * rather than large.
   */
  openInterestChangeRatio: number | null;
  changePct: number;
  quadrant: Quadrant;
}

/** The quadrant chart's points — only names that actually landed in a quadrant. */
export function futuresPoints(rows: BistPositioningRow[]): FuturesPoint[] {
  const points: FuturesPoint[] = [];
  for (const row of rows) {
    const quadrant = quadrantOf(row);
    if (quadrant === null) continue;
    if (row.open_interest_change === null || row.change_pct === null) continue;
    const openInterest = row.open_interest ?? 0;
    const previous = openInterest - row.open_interest_change;
    points.push({
      ticker: row.ticker,
      sector: row.sector,
      openInterest,
      openInterestChange: row.open_interest_change,
      openInterestChangeRatio: previous > 0 ? row.open_interest_change / previous : null,
      changePct: row.change_pct,
      quadrant,
    });
  }
  return points;
}

// ── Shared ─────────────────────────────────────────────────────────────────

/** The middle value, averaging the two middles on an even count. Null if empty. */
export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}
