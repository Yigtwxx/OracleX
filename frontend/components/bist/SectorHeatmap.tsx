'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import type { BistSector } from '@/lib/bist-api';
import { formatCompactTry, formatPercent, formatSignedPercent } from '@/lib/bist-format';
import { insetTile, squarify } from '@/lib/treemap';

interface SectorHeatmapProps {
  sectors: BistSector[];
  height?: number;
}

/**
 * Where the money went today, by sector.
 *
 * A treemap rather than a bar chart because two quantities matter at once — how
 * much of the market a sector is, and which way it moved — and area carries the
 * first without spending a second axis on it.
 *
 * Built on `lib/treemap.ts` (`squarify`, `insetTile`) and positioned divs
 * rather than ECharts, which is the choice `components/overview/AdvancedHeatmap.tsx`
 * already made: a treemap of thirty tiles needs hover, focus and text that
 * reflows, and all three are cheaper in the DOM than in a canvas.
 *
 * The colour ramp is the semantic up/down pair at four opacities rather than
 * the `--heat-*` sequence, because the quantity encoded is signed. A sequential
 * ramp would make a small loss and a small gain look like neighbours.
 */
export default function SectorHeatmap({ sectors, height = 320 }: SectorHeatmapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      setWidth(entries[0]?.contentRect.width ?? 0);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // `squarify` speaks in ids and values only — geometry, no domain — so the
  // sector is looked back up by id afterwards rather than smuggled through.
  const bySector = useMemo(
    () => new Map(sectors.map((sector) => [sector.sector, sector])),
    [sectors]
  );

  const tiles = useMemo(() => {
    if (width <= 0) return [];
    const items = sectors
      .filter((sector) => sector.market_cap > 0)
      .map((sector) => ({ id: sector.sector, value: sector.market_cap }));
    return squarify(items, width, height).map((tile) => insetTile(tile, 2));
  }, [sectors, width, height]);

  return (
    <div ref={containerRef} style={{ height }} className="relative w-full">
      {tiles.map((tile) => {
        const sector = bySector.get(tile.id);
        if (!sector) return null;

        const change = sector.change_pct;
        const magnitude = Math.min(1, Math.abs(change ?? 0) / 0.03);
        const opacity = 0.18 + magnitude * 0.55;
        const background =
          change === null
            ? 'var(--surface-2)'
            : change >= 0
              ? `color-mix(in srgb, var(--up) ${Math.round(opacity * 100)}%, transparent)`
              : `color-mix(in srgb, var(--down) ${Math.round(opacity * 100)}%, transparent)`;

        const roomForDetail = tile.w > 96 && tile.h > 52;

        return (
          <div
            key={tile.id}
            title={`${sector.sector} · ${formatCompactTry(sector.market_cap)} · ağırlık ${formatPercent(sector.weight)} · ${sector.advancers}▲ ${sector.decliners}▼`}
            style={{
              position: 'absolute',
              left: tile.x,
              top: tile.y,
              width: tile.w,
              height: tile.h,
              background,
            }}
            className="overflow-hidden rounded border border-line px-2 py-1"
          >
            <p className="truncate text-2xs font-medium text-fg">{sector.sector}</p>
            {roomForDetail && (
              <>
                <p className="tabnum truncate text-sm font-semibold text-fg">
                  {formatSignedPercent(change)}
                </p>
                <p className="tabnum truncate text-2xs text-fg-muted">
                  {formatPercent(sector.weight, 1)}
                </p>
              </>
            )}
          </div>
        );
      })}
      {tiles.length === 0 && (
        <p className="flex h-full items-center justify-center text-sm text-fg-subtle">
          Sektör verisi yok.
        </p>
      )}
    </div>
  );
}
