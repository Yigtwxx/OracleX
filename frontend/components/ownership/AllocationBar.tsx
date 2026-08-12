'use client';

import type { OwnershipAllocationSlice } from '@/lib/api';
import { ASSET_CLASS_LABEL, allocationColors, formatUsd } from './format';

interface AllocationBarProps {
  slices: OwnershipAllocationSlice[];
  /** Renders the holding names beneath the bar. Off on the grid card — no room. */
  showLegend?: boolean;
  className?: string;
}

/**
 * How one entity's known value splits across its holdings.
 *
 * One colour per holding, not per asset class. A treasury that is 50% ETH, 30%
 * BTC and 20% cash has three segments here; grouping by class would draw the
 * two coins as one and produce the same bar as a pure-bitcoin treasury.
 *
 * Two further choices:
 *
 * A slice never rounds itself out of existence. A 0.3% holding would compute to
 * a sub-pixel width and disappear, which reads identically to not holding the
 * asset at all — so every present slice gets at least 2px. The bar is a
 * proportion, but its first job is to say what is there.
 *
 * An entity with nothing priced gets a flat rule rather than a bar. Drawing a
 * full-width "other" segment would invent a composition out of missing data.
 */
export default function AllocationBar({
  slices,
  showLegend = false,
  className = '',
}: AllocationBarProps) {
  if (slices.length === 0) {
    return (
      <div
        className={`h-1.5 w-full rounded-sm bg-surface-2 ${className}`}
        title="No priced holdings"
      />
    );
  }

  // Resolved for the bar as a whole: the colours are chosen against each other
  // so no two segments in one bar can land on the same fill.
  const colors = allocationColors(slices);
  const labelFor = (slice: OwnershipAllocationSlice) =>
    slice.label || ASSET_CLASS_LABEL[slice.asset_class];

  return (
    <div className={className}>
      {/* No gap between segments: a gutter would push the row past 100% and
          flex would shrink every width to fit, which is a small lie about a
          proportion. The colours do the separating. */}
      <div className="flex h-1.5 w-full overflow-hidden rounded-sm bg-surface-2">
        {slices.map((slice, index) => (
          <div
            key={slice.key || slice.asset_class}
            className={colors[index].fill}
            style={{
              width: `${slice.pct}%`,
              minWidth: '2px',
              // A brand's colour is a value, not a token, so it is set here
              // rather than through a class Tailwind would have to generate.
              backgroundColor: colors[index].hex,
            }}
            title={`${labelFor(slice)} — ${formatUsd(slice.value_usd)} (${slice.pct.toFixed(1)}%)`}
          />
        ))}
      </div>

      {showLegend && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          {slices.map((slice, index) => (
            <span
              key={slice.key || slice.asset_class}
              className="flex items-center gap-1.5 text-2xs text-fg-muted"
            >
              <span
                className={`h-2 w-2 shrink-0 rounded-sm ${colors[index].fill}`}
                style={{ backgroundColor: colors[index].hex }}
                aria-hidden
              />
              <span className="truncate" style={{ color: colors[index].hex }}>
                {labelFor(slice)}
              </span>
              <span className="tabnum text-fg-subtle">{slice.pct.toFixed(1)}%</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
