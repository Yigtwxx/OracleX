'use client';

import type { BistOwnershipSlice } from '@/lib/bist-api';
import { formatPercent } from '@/lib/bist-format';
import { allocationSegments, allocationSummary } from '@/lib/bist-ownership';

interface OwnerAllocationBarProps {
  slices: BistOwnershipSlice[];
  height?: 'thin' | 'wide';
  showLegend?: boolean;
  className?: string;
}

/**
 * How one holder's known lira value splits across its stakes.
 *
 * The three rules are inherited from `components/ownership/AllocationBar.tsx`
 * and `FundAllocationBar.tsx`, restated so they are not rediscovered here: a
 * present segment keeps at least 2px so a small stake does not vanish into
 * "not held"; there is no gutter, because a gutter pushes the row past 100%
 * and shrinks every width into a small lie; and a holder nothing could be
 * valued for gets a flat rule, not a full-width "other".
 */
export default function OwnerAllocationBar({
  slices,
  height = 'thin',
  showLegend = false,
  className = '',
}: OwnerAllocationBarProps) {
  const segments = allocationSegments(slices);
  const barHeight = height === 'wide' ? 'h-2.5' : 'h-1.5';

  if (segments.length === 0) {
    return (
      <div className={className}>
        <div
          className={`${barHeight} w-full rounded-full border border-dashed border-line`}
          role="img"
          aria-label="Değerlenebilen pozisyon yok"
        />
      </div>
    );
  }

  return (
    <div className={className}>
      <div
        className={`flex ${barHeight} w-full overflow-hidden rounded-full bg-surface-2`}
        role="img"
        aria-label={allocationSummary(segments)}
      >
        {segments.map((segment) => (
          <span
            key={segment.key}
            className="h-full"
            style={{
              width: `${segment.pct * 100}%`,
              minWidth: 2,
              background: segment.color,
              opacity: segment.pooled ? 0.45 : 1,
            }}
          />
        ))}
      </div>
      {showLegend && (
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
          {segments.map((segment) => (
            <li key={segment.key} className="flex items-center gap-1.5 text-2xs text-fg-muted">
              <span
                className="inline-block h-2 w-2 rounded-sm"
                style={{ background: segment.color, opacity: segment.pooled ? 0.45 : 1 }}
                aria-hidden="true"
              />
              <span className={segment.pooled ? 'text-fg-subtle' : 'text-fg'}>
                {segment.ticker ?? segment.label}
              </span>
              <span className="tabnum">
                {formatPercent(segment.pct, segment.pct < 0.1 ? 1 : 0)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
