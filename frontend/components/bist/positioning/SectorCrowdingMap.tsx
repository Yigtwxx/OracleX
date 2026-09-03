'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { formatNumber } from '@/lib/bist-format';
import type { SectorAggregate } from '@/lib/bist-positioning';
import { insetTile, squarify } from '@/lib/treemap';

interface SectorCrowdingMapProps {
  sectors: SectorAggregate[];
  selected?: string;
  onSelect: (sector: string | undefined) => void;
  height?: number;
}

/**
 * Steps of median relative volume, shared by the tiles and the legend.
 *
 * One array so the two cannot drift — the same reason `lib/heatmap-scale.ts`
 * feeds its buckets to both. The cuts are set against where sector medians
 * actually fall — a band roughly from 1.2× to 2.5× — rather than at round
 * numbers: the first version cut at 1.2/1.6/2.2 and put every sector on the
 * board into two adjacent shades, which reads as one flat colour and wastes
 * half the ramp. The quantity is unsigned magnitude ("how unusual
 * is the turnover here"), so it takes the sequential ramp rather than the
 * up/down pair: nothing on this map is a gain or a loss.
 */
const VOLUME_STEPS = [
  { min: 2.0, token: 'var(--heat-seq-4)', label: '2×+' },
  { min: 1.7, token: 'var(--heat-seq-3)', label: '1.7×' },
  { min: 1.4, token: 'var(--heat-seq-2)', label: '1.4×' },
  { min: 0, token: 'var(--heat-seq-1)', label: '<1.4×' },
] as const;

function fillFor(medianRelativeVolume: number | null): string {
  if (medianRelativeVolume === null) return 'var(--surface-2)';
  return (
    VOLUME_STEPS.find((step) => medianRelativeVolume >= step.min)?.token ?? 'var(--heat-seq-1)'
  );
}

/**
 * Where the crowding is concentrated.
 *
 * Area is summed crowding rather than market capitalisation, which is the
 * whole point of having this next to the sector map on the overview page. A map
 * sized by capitalisation would put banking and holdings at the centre every
 * single day, because that is what the index is made of. Sized by crowding it
 * only shows a sector large when that sector is where the unusual turnover
 * actually is — and a quiet sector correctly disappears.
 *
 * Positioned divs over `lib/treemap.ts`, matching `SectorHeatmap` and
 * `overview/AdvancedHeatmap`: each tile has to be a pressable, focusable filter
 * with text that reflows, and all three are cheaper in the DOM than in canvas.
 */
export default function SectorCrowdingMap({
  sectors,
  selected,
  onSelect,
  height = 200,
}: SectorCrowdingMapProps) {
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

  const bySector = useMemo(
    () => new Map(sectors.map((sector) => [sector.sector, sector])),
    [sectors]
  );

  const tiles = useMemo(() => {
    if (width <= 0) return [];
    const items = sectors
      .filter((sector) => sector.crowding > 0)
      .map((sector) => ({ id: sector.sector, value: sector.crowding }));
    return squarify(items, width, height).map((tile) => insetTile(tile, 2));
  }, [sectors, width, height]);

  return (
    <div className="flex flex-col gap-2 p-3">
      {/* `overflow-hidden` is load-bearing at narrow widths: `squarify` lays the
          tiles out in floats, and the accumulated rounding on the last column
          can put its right edge a few pixels past the measured width. Clipping
          costs nothing — the spill is sub-pixel — and without it the panel is
          the one element on the page that scrolls sideways on a phone. */}
      <div ref={containerRef} style={{ height }} className="relative w-full overflow-hidden">
        {tiles.map((tile) => {
          const sector = bySector.get(tile.id);
          if (!sector) return null;

          const active = selected === sector.sector;
          const dimmed = selected !== undefined && !active;
          const label = `${sector.sector}: ${sector.count} hisse, toplam kalabalıklık ${formatNumber(
            sector.crowding,
            1
          )}, medyan nispi hacim ${formatNumber(sector.medianRelativeVolume, 2)}×`;
          const roomForDetail = tile.w > 84 && tile.h > 44;
          // Below this a name renders as one truncated letter, which is noise
          // rather than a label. The tile keeps its colour and its area, and
          // the name stays reachable through the tooltip and the aria-label.
          const roomForName = tile.w > 56 && tile.h > 22;

          return (
            <button
              key={tile.id}
              type="button"
              aria-pressed={active}
              aria-label={label}
              title={label}
              onClick={() => onSelect(active ? undefined : sector.sector)}
              style={{
                position: 'absolute',
                left: tile.x,
                top: tile.y,
                width: tile.w,
                height: tile.h,
                background: fillFor(sector.medianRelativeVolume),
                opacity: dimmed ? 0.35 : 1,
                borderColor: active ? 'var(--fg)' : 'var(--border)',
              }}
              className="overflow-hidden rounded border px-2 py-1 text-left transition-opacity"
            >
              {roomForName && (
                <span className="block truncate text-2xs font-medium text-fg">{sector.sector}</span>
              )}
              {roomForDetail && (
                <>
                  <span className="tabnum block truncate text-sm font-semibold text-fg">
                    {formatNumber(sector.medianRelativeVolume, 1)}×
                  </span>
                  <span className="tabnum block truncate text-2xs text-fg-muted">
                    {sector.count} hisse
                  </span>
                </>
              )}
            </button>
          );
        })}
        {tiles.length === 0 && (
          <p className="flex h-full items-center justify-center px-4 text-center text-sm text-fg-subtle">
            Ölçülebilir kalabalıklık taşıyan sektör yok.
          </p>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 text-2xs text-fg-subtle">
        <span>medyan nispi hacim</span>
        {[...VOLUME_STEPS].reverse().map((step) => (
          <span key={step.label} className="inline-flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: step.token }}
              aria-hidden="true"
            />
            {step.label}
          </span>
        ))}
      </div>
    </div>
  );
}
