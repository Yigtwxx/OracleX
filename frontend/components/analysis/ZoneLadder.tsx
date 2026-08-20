import type { PriceZone } from '@/store/useStore';
import {
  confirmedOn,
  formatBand,
  formatLevel,
  formatSignedPercent,
  horizonLabel,
} from '@/lib/technical-format';

type Side = 'resistance' | 'support' | 'inside';

const SIDE_STYLE: Record<Side, { band: string; fill: string; label: string }> = {
  resistance: { band: 'text-down', fill: 'bg-down', label: 'Resistance' },
  support: { band: 'text-up', fill: 'bg-up', label: 'Support' },
  inside: { band: 'text-warn', fill: 'bg-warn', label: 'Price is inside' },
};

/** One band, with everything that earns it a place and nothing else. */
function ZoneRow({ zone, side }: { zone: PriceZone; side: Side }) {
  const style = SIDE_STYLE[side];
  const meta = [
    `${zone.touches} ${zone.touches === 1 ? 'touch' : 'touches'}`,
    confirmedOn(zone),
    zone.flip ? 'flipped' : null,
  ].filter(Boolean) as string[];

  return (
    <li className="py-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className={`font-mono text-sm tabnum ${style.band}`}>{formatBand(zone)}</span>
        <span className="font-mono text-sm tabnum text-fg-muted">
          {formatSignedPercent(zone.distance_percent)}
        </span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="label shrink-0">{horizonLabel(zone.horizon)}</span>
        {/* Deliberately narrow and fixed-width. Stretched across the row it read
            as the band's extent — a second price claim — when all it says is how
            much attention the band has earned, which the figure beside it
            already states. */}
        <span className="relative h-0.5 w-10 shrink-0 rounded-full bg-surface-2" aria-hidden="true">
          <span
            className={`absolute inset-y-0 left-0 rounded-full opacity-60 ${style.fill}`}
            style={{ width: `${Math.min(100, Math.max(0, zone.strength))}%` }}
          />
        </span>
        <span className="text-2xs tabnum text-fg-subtle">
          strength {zone.strength} · {meta.join(' · ')}
        </span>
      </div>
    </li>
  );
}

/**
 * The bands around the current price, as a ladder.
 *
 * Resistance above, price in the middle, support below — the arrangement is the
 * point. Two flat chip rows, which is what this replaced, left the reader to
 * work out which side of spot each level was on and how far away it was; a
 * ladder answers both by position.
 */
export default function ZoneLadder({
  resistance,
  support,
  inside,
  price,
}: {
  resistance: PriceZone[];
  support: PriceZone[];
  inside: PriceZone[];
  price?: number | null;
}) {
  if (!resistance.length && !support.length && !inside.length) return null;

  // The API sends each side nearest-first. Overhead bands read top-down from
  // the furthest away, so that the one just above spot sits next to the spot row.
  const overhead = [...resistance].reverse();

  return (
    <div>
      <h5 className="label mb-1">Zones</h5>

      {overhead.length > 0 && (
        <ul role="list" className="divide-y divide-line">
          {overhead.map((zone) => (
            <ZoneRow key={`r-${zone.low}-${zone.high}`} zone={zone} side="resistance" />
          ))}
        </ul>
      )}

      {typeof price === 'number' && (
        <div className="my-1.5 flex items-center gap-2">
          <span className="h-px flex-1 bg-line-strong" aria-hidden="true" />
          <span className="font-mono text-sm tabnum text-fg">{formatLevel(price)}</span>
          <span className="label">now</span>
          <span className="h-px flex-1 bg-line-strong" aria-hidden="true" />
        </div>
      )}

      {inside.length > 0 && (
        <ul role="list" className="divide-y divide-line">
          {inside.map((zone) => (
            <ZoneRow key={`i-${zone.low}-${zone.high}`} zone={zone} side="inside" />
          ))}
        </ul>
      )}

      {support.length > 0 ? (
        <ul role="list" className="divide-y divide-line">
          {support.map((zone) => (
            <ZoneRow key={`s-${zone.low}-${zone.high}`} zone={zone} side="support" />
          ))}
        </ul>
      ) : (
        <p className="py-1.5 text-sm text-fg-subtle">
          No band below the current price — nothing has been tested as support here.
        </p>
      )}
    </div>
  );
}
