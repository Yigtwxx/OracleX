'use client';

import type { BistHeatmapTile } from '@/lib/bist-api';
import { formatCompactTry } from '@/lib/bist-format';
import { BIST_METRIC_CONFIG, bucketForTile, oiBadge, tileDescription } from '@/lib/bist-heatmap';
import type { BistHeatMetric } from '@/lib/bist-heatmap';
import { insetTile, type TreemapTile } from '@/lib/treemap';

/** Gutter between tiles, applied as an inset so it never distorts the areas. */
export const TILE_GAP = 3;

interface HeatmapTileProps {
  tile: BistHeatmapTile;
  rect: TreemapTile;
  metric: BistHeatMetric;
  selected: boolean;
  onSelect: (tile: BistHeatmapTile) => void;
}

/**
 * One company on the board.
 *
 * A real `<button>` rather than a shape in a canvas: at a hundred tiles the
 * board has to be reachable by keyboard, and the text inside has to reflow.
 * That is the same call `components/overview/AdvancedHeatmap.tsx` made.
 *
 * The colour comes from `bg-heat-*` and not from the `color-mix` ramp
 * `SectorHeatmap` uses. Two reasons, and both are specific to this board: it
 * carries a legend, and the legend can only agree with the tiles if both read
 * the same array; and every stop in the `--heat-*` ramps ships with an ink
 * class whose contrast was measured against it, which matters here because
 * there is always text on top of a tile.
 */
export default function HeatmapTile({ tile, rect, metric, selected, onSelect }: HeatmapTileProps) {
  const bucket = bucketForTile(tile, metric);
  const { x, y, w, h } = insetTile(rect, TILE_GAP);

  // Chosen by measured size rather than by rank: a tile is legible or it is
  // not, and that depends on the box it got, not on where it sorted.
  const showSymbol = w >= 30 && h >= 18;
  const showValue = w >= 56 && h >= 40;
  const showDetail = w >= 96 && h >= 68;

  // Wider than `showValue`, because the badge and the ticker share one line and
  // the badge does not shrink. At the `showValue` threshold it won the row and
  // pushed "SASA" out as "S…" — the identifier losing to the annotation about
  // it. The ticker gets the width first; open interest is in the tooltip, the
  // detail panel and the aria-label regardless.
  const badge = w >= 112 && showValue ? oiBadge(tile) : null;

  return (
    <button
      type="button"
      onClick={() => onSelect(tile)}
      onFocus={() => onSelect(tile)}
      aria-label={tileDescription(tile, metric)}
      style={{ position: 'absolute', left: x, top: y, width: w, height: h }}
      className={`overflow-hidden rounded px-1.5 py-1 text-left transition-shadow ${bucket.className} ${
        selected ? 'ring-1 ring-fg/50' : ''
      }`}
    >
      {showSymbol && (
        <span className="flex items-start justify-between gap-1">
          <span className="truncate text-2xs font-semibold">{tile.ticker}</span>
          {badge && (
            <span title={badge.title} className="shrink-0 text-[9px] opacity-80">
              {badge.text}
            </span>
          )}
        </span>
      )}
      {showValue && (
        <span className="tabnum block truncate text-sm font-semibold">
          {BIST_METRIC_CONFIG[metric].display(tile)}
        </span>
      )}
      {showDetail && (
        <span className="tabnum block truncate text-2xs opacity-80">
          {formatCompactTry(tile.market_cap)}
        </span>
      )}
    </button>
  );
}
