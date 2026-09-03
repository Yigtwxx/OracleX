'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import type { BistHeatmapTile } from '@/lib/bist-api';
import type { BistHeatMetric } from '@/lib/bist-heatmap';
import { squarify } from '@/lib/treemap';
import HeatmapTile from './HeatmapTile';

interface HeatmapBoardProps {
  tiles: BistHeatmapTile[];
  metric: BistHeatMetric;
  selectedTicker?: string;
  onSelect: (tile: BistHeatmapTile) => void;
  /** Fixed height for the sector view's small boards; omitted, the board fills its parent. */
  height?: number;
}

/**
 * The treemap itself: measure, lay out, place.
 *
 * `lib/treemap.ts` speaks in ids and values only — geometry, no domain — so the
 * company is looked back up by ticker after the layout rather than smuggled
 * through it. A listing with no capitalisation has no area and `squarify` drops
 * it; it is still reachable through the detail panel, and dropping it from the
 * layout is honest about the one thing the board cannot draw.
 */
export default function HeatmapBoard({
  tiles,
  metric,
  selectedTicker,
  onSelect,
  height,
}: HeatmapBoardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      setSize({ width: rect?.width ?? 0, height: rect?.height ?? 0 });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const byTicker = useMemo(() => new Map(tiles.map((tile) => [tile.ticker, tile])), [tiles]);

  const boardHeight = height ?? size.height;

  const rects = useMemo(() => {
    if (size.width <= 0 || boardHeight <= 0) return [];
    return squarify(
      tiles.map((tile) => ({ id: tile.ticker, value: tile.market_cap ?? 0 })),
      size.width,
      boardHeight
    );
  }, [tiles, size.width, boardHeight]);

  return (
    <div
      ref={containerRef}
      style={height === undefined ? undefined : { height }}
      className={`relative w-full ${height === undefined ? 'h-full' : ''}`}
    >
      {rects.map((rect) => {
        const tile = byTicker.get(rect.id);
        if (!tile) return null;
        return (
          <HeatmapTile
            key={rect.id}
            tile={tile}
            rect={rect}
            metric={metric}
            selected={tile.ticker === selectedTicker}
            onSelect={onSelect}
          />
        );
      })}
    </div>
  );
}
