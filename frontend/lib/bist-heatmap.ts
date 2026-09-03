/**
 * The BIST heatmap's colour scales and the derivations behind a tile.
 *
 * Everything here is pure, and that is the point: the vitest config collects
 * only the test files under `lib/`, so a rule that lives inside a component is
 * a rule nothing checks. The unit conversion below is the single most dangerous
 * line in the feature and it needs a test more than it needs a home in the
 * component that uses it.
 *
 * **Why the scales are here and not in `lib/heatmap-scale.ts`.** That file is
 * the global realm's, in the same way `lib/bist-format.ts` exists beside the
 * English formatters rather than inside them. Three things differ:
 *
 * 1. The labels are Turkish and the percent sign leads — `%+5 ve üzeri`, never
 *    `≥ +5%`.
 * 2. The bounds have to match the market. Borsa İstanbul caps a daily move at
 *    ±10% (`DAILY_LIMIT`), so `PRICE_SCALE`'s ±5% top stop would pile half the
 *    board into the brightest bucket on any trending day.
 * 3. The turnover metric here is raw lira. `VOLUME_SCALE` reads a 0-100 log
 *    score and `TURNOVER_SCALE` a percent of market cap; neither fits.
 *
 * What *is* reused is the mechanism — `HeatBucket`, `bucketFor`,
 * `UNKNOWN_BUCKET` and the `bg-heat-*` ramps whose ink pairs are contrast
 * matched in globals.css.
 */

import { Layers, TrendingUp, Wallet } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type { BistHeatmapSector, BistHeatmapTile } from '@/lib/bist-api';
import { bucketFor, UNKNOWN_BUCKET, type HeatBucket } from '@/lib/heatmap-scale';
import { EMPTY, formatCompact, formatCompactTry, formatSignedPercent } from '@/lib/bist-format';

export type BistHeatMetric = 'change' | 'traded_value' | 'open_interest';

/**
 * Diverging, in percent.
 *
 * The stops are spaced against the ±10% daily limit rather than copied from the
 * crypto board: a name at +7% is at the edge of what this market allows in a
 * session, and that is what the brightest stop should mean.
 */
export const BIST_CHANGE_SCALE: readonly HeatBucket[] = [
  { min: 7, className: 'bg-heat-up-4 text-bg', label: '%+7 ve üzeri' },
  { min: 4, className: 'bg-heat-up-3 text-fg', label: '%+4 … %+7' },
  { min: 1.5, className: 'bg-heat-up-2 text-fg', label: '%+1,5 … %+4' },
  { min: 0, className: 'bg-heat-up-1 text-fg', label: '%0 … %+1,5' },
  { min: -1.5, className: 'bg-heat-down-1 text-fg', label: '%-1,5 … %0' },
  { min: -4, className: 'bg-heat-down-2 text-fg', label: '%-4 … %-1,5' },
  { min: -7, className: 'bg-heat-down-3 text-fg', label: '%-7 … %-4' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-down-4 text-bg', label: '%-7 ve altı' },
] as const;

/**
 * Sequential, in lira. Turnover has magnitude but no direction.
 *
 * The bounds are the figures themselves rather than a normalised score, so the
 * legend names real money — which is also what each tile prints.
 *
 * Anchored against a live board rather than picked round. A first attempt at
 * 5 mr / 1 mr / 250 mn left the brightest bucket empty on all three indices —
 * the busiest name on the XU100 turns over about 4 mr ₺ — which makes the top
 * of the ramp unreachable and squeezes two thirds of the board into the darkest
 * stop. These stops fill all four on the XU100 and the XUTUM. The XUTUM's own
 * distribution sits an order of magnitude below the XU030's, so no single set
 * of bounds fills every bucket on every index; the empty bottom bucket on the
 * BIST 30 is a true statement about the BIST 30 rather than a broken scale.
 */
export const BIST_TURNOVER_SCALE: readonly HeatBucket[] = [
  { min: 2e9, className: 'bg-heat-seq-4 text-bg', label: '2 mr ₺ ve üzeri' },
  { min: 500e6, className: 'bg-heat-seq-3 text-fg', label: '500 mn – 2 mr ₺' },
  { min: 100e6, className: 'bg-heat-seq-2 text-fg', label: '100 – 500 mn ₺' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-seq-1 text-fg', label: '100 mn ₺ altı' },
] as const;

/**
 * Diverging, in percent of yesterday's open interest.
 *
 * Signed, so it takes the up/down ramp rather than the sequential one: a
 * position being built and a position being closed are opposite events, and a
 * sequential ramp would draw them as neighbours. The bounds are tighter than
 * the price scale's because open interest moves in smaller relative steps.
 */
export const BIST_OI_SCALE: readonly HeatBucket[] = [
  { min: 10, className: 'bg-heat-up-4 text-bg', label: '%+10 ve üzeri' },
  { min: 3, className: 'bg-heat-up-3 text-fg', label: '%+3 … %+10' },
  { min: 0, className: 'bg-heat-up-2 text-fg', label: '%0 … %+3' },
  { min: -3, className: 'bg-heat-down-2 text-fg', label: '%-3 … %0' },
  { min: -10, className: 'bg-heat-down-3 text-fg', label: '%-10 … %-3' },
  { min: Number.NEGATIVE_INFINITY, className: 'bg-heat-down-4 text-bg', label: '%-10 ve altı' },
] as const;

/**
 * The tile's value in the unit its scale is written in.
 *
 * **This function holds the only `* 100` in the feature.** Every `/api/bist/*`
 * payload carries fractions, `bist-format` expects fractions, and only the
 * scale bounds above are written in percent — because a reader reads
 * "%+3 … %+7", not "0,03 … 0,07". Converting at the scale's edge and nowhere
 * else is what keeps the two conventions from meeting in the middle: multiply
 * twice and `0,024` becomes 240, the tile lands in the brightest bucket, and
 * nothing throws, because 240 is a perfectly good number.
 *
 * `null` becomes `undefined` so `bucketFor` reaches `UNKNOWN_BUCKET` rather
 * than treating a missing reading as a measured zero.
 */
export function metricValue(tile: BistHeatmapTile, metric: BistHeatMetric): number | undefined {
  switch (metric) {
    case 'change':
      return tile.change_pct === null ? undefined : tile.change_pct * 100;
    case 'open_interest':
      return tile.open_interest_change_pct === null
        ? undefined
        : tile.open_interest_change_pct * 100;
    case 'traded_value':
      return tile.traded_value === null ? undefined : tile.traded_value;
  }
}

interface BistMetricConfig {
  label: string;
  icon: LucideIcon;
  scale: readonly HeatBucket[];
  /** What the tile prints. Always a real unit, never the bucket's bound. */
  display: (tile: BistHeatmapTile) => string;
  /** Shown when no tile on the board has a reading for this metric. */
  emptyHint: string;
  /**
   * Whether a name without futures counts as unmeasured for this metric.
   *
   * On the open-interest metric it does: there is genuinely nothing to colour,
   * and the dashed "no data" treatment says so. On price and turnover it does
   * not — having no futures says nothing about a stock's move, and dimming half
   * the board for it would invent a distinction the metric does not carry.
   */
  unknownWithoutFutures: boolean;
}

export const BIST_METRIC_CONFIG: Record<BistHeatMetric, BistMetricConfig> = {
  change: {
    label: 'Günlük değişim',
    icon: TrendingUp,
    scale: BIST_CHANGE_SCALE,
    display: (tile) => formatSignedPercent(tile.change_pct),
    emptyHint: 'Bu endekste hiçbir hisse için günlük değişim bildirilmemiş.',
    unknownWithoutFutures: false,
  },
  traded_value: {
    label: 'İşlem hacmi',
    icon: Wallet,
    scale: BIST_TURNOVER_SCALE,
    display: (tile) => formatCompactTry(tile.traded_value),
    emptyHint: 'Bu endekste hiçbir hisse için işlem hacmi bildirilmemiş.',
    unknownWithoutFutures: false,
  },
  open_interest: {
    label: 'VİOP açık pozisyon',
    icon: Layers,
    scale: BIST_OI_SCALE,
    display: (tile) => (tile.open_interest === null ? EMPTY : formatCompact(tile.open_interest)),
    emptyHint:
      'VİOP tek hisse vadelileri yaklaşık kırk dayanağa açık; bu kapsamda ' +
      'açık pozisyon taşıyan hisse yok.',
    unknownWithoutFutures: true,
  },
};

/** The bucket a tile falls in for one metric. */
export function bucketForTile(tile: BistHeatmapTile, metric: BistHeatMetric): HeatBucket {
  if (BIST_METRIC_CONFIG[metric].unknownWithoutFutures && !tile.has_futures) {
    return UNKNOWN_BUCKET;
  }
  return bucketFor(metricValue(tile, metric), BIST_METRIC_CONFIG[metric].scale);
}

/** Whether any tile on the board has a reading for this metric. */
export function metricIsEmpty(tiles: BistHeatmapTile[], metric: BistHeatMetric): boolean {
  return tiles.every((tile) => metricValue(tile, metric) === undefined);
}

export interface BistHeatmapGroup {
  sector: BistHeatmapSector;
  tiles: BistHeatmapTile[];
}

/**
 * Tiles folded onto the sector rows the server ranked.
 *
 * Sectors arrive largest first and keep that order. A tile naming a sector the
 * payload does not carry still gets drawn — under a synthesised row rather than
 * dropped, because a board that silently loses a company stops summing to the
 * index it claims to be.
 */
export function groupBySector(
  tiles: BistHeatmapTile[],
  sectors: BistHeatmapSector[]
): BistHeatmapGroup[] {
  const groups = new Map<string, BistHeatmapGroup>();
  for (const sector of sectors) {
    groups.set(sector.sector, { sector, tiles: [] });
  }

  for (const tile of tiles) {
    let group = groups.get(tile.sector);
    if (!group) {
      group = {
        sector: {
          sector: tile.sector,
          count: 0,
          market_cap: 0,
          weight: 0,
          change_pct: null,
          advancers: 0,
          decliners: 0,
        },
        tiles: [],
      };
      groups.set(tile.sector, group);
    }
    group.tiles.push(tile);
  }

  return Array.from(groups.values()).filter((group) => group.tiles.length > 0);
}

/**
 * The open-interest chip a tile carries, or nothing.
 *
 * Present whenever the name has a position, even with no change to report:
 * "there is a position here and it did not move" is a reading, and blanking it
 * would make an unmoved position look like no futures at all.
 */
export function oiBadge(tile: BistHeatmapTile): { text: string; title: string } | null {
  if (!tile.has_futures || tile.open_interest === null) return null;

  const change = tile.open_interest_change;
  const arrow = change === null || change === 0 ? '·' : change > 0 ? '▲' : '▼';
  const relative = tile.open_interest_change_pct;

  return {
    text: `${arrow}${relative === null ? '' : ` ${formatSignedPercent(relative)}`}`,
    title:
      `VİOP açık pozisyon ${formatCompact(tile.open_interest)} kontrat · ` +
      `${tile.contracts} vade · günlük değişim ` +
      `${change === null ? EMPTY : formatCompact(change)}`,
  };
}

/** What a screen reader hears instead of the tile's cramped visible text. */
export function tileDescription(tile: BistHeatmapTile, metric: BistHeatMetric): string {
  const config = BIST_METRIC_CONFIG[metric];
  const futures = tile.has_futures
    ? `VİOP açık pozisyon ${formatCompact(tile.open_interest)} kontrat.`
    : 'VİOP kontratı yok.';

  return [
    `${tile.name} (${tile.ticker}).`,
    `Piyasa değeri ${formatCompactTry(tile.market_cap)}.`,
    `${config.label} ${config.display(tile)}.`,
    `Sektör ${tile.sector}.`,
    futures,
  ].join(' ');
}
