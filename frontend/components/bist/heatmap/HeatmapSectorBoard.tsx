'use client';

import { useMemo } from 'react';

import type { BistHeatmapSector, BistHeatmapTile } from '@/lib/bist-api';
import { formatCompactTry, formatPercent, formatSignedPercent } from '@/lib/bist-format';
import { groupBySector, type BistHeatMetric } from '@/lib/bist-heatmap';
import HeatmapBoard from './HeatmapBoard';

interface HeatmapSectorBoardProps {
  tiles: BistHeatmapTile[];
  sectors: BistHeatmapSector[];
  metric: BistHeatMetric;
  selectedTicker?: string;
  onSelect: (tile: BistHeatmapTile) => void;
}

/**
 * The same tiles, partitioned by sector.
 *
 * Each sector gets its own small treemap rather than a single board with
 * borders drawn on it: inside a section the areas are comparable to each other,
 * which is the comparison a reader is making once they have chosen a sector.
 * The weighted move in the header comes from the server over the whole index,
 * not from the tiles on screen, so `limit` cannot quietly change it.
 */
export default function HeatmapSectorBoard({
  tiles,
  sectors,
  metric,
  selectedTicker,
  onSelect,
}: HeatmapSectorBoardProps) {
  const groups = useMemo(() => groupBySector(tiles, sectors), [tiles, sectors]);

  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <section key={group.sector.sector} className="surface surface-flat overflow-hidden">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-line px-3 py-1.5">
            <h3 className="text-sm font-semibold text-fg">{group.sector.sector}</h3>
            <div className="flex items-baseline gap-3 text-2xs text-fg-muted">
              <span className="tabnum">{group.tiles.length} hisse</span>
              <span className="tabnum">{formatCompactTry(group.sector.market_cap)}</span>
              <span className="tabnum">{formatPercent(group.sector.weight)} ağırlık</span>
              <span className="tabnum font-medium text-fg">
                {formatSignedPercent(group.sector.change_pct)}
              </span>
            </div>
          </div>
          <div className="p-2">
            <HeatmapBoard
              tiles={group.tiles}
              metric={metric}
              selectedTicker={selectedTicker}
              onSelect={onSelect}
              height={140}
            />
          </div>
        </section>
      ))}
    </div>
  );
}
