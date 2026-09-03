'use client';

import { allocationSummary, formatWeight, type FundAllocationSegment } from '@/lib/fund-allocation';
import { formatPercent } from '@/lib/bist-format';

interface FundAllocationBarProps {
  segments: FundAllocationSegment[];
  /**
   * The fraction TEFAS reported, summed. Below 1 the remainder stays as bare
   * track — the bar is never stretched to fill, because the shortfall is a
   * fact about the filing rather than a rounding artefact to hide.
   */
  total: number;
  /** `thin` in the screener row, `wide` on the detail card. */
  height?: 'thin' | 'wide';
  showLegend?: boolean;
  className?: string;
}

/**
 * What one fund is actually holding, as one stacked bar.
 *
 * Three behaviours are inherited deliberately from
 * `components/ownership/AllocationBar.tsx`, and the reasoning is repeated here
 * so it is not rediscovered by someone editing only this file:
 *
 * A segment never rounds itself out of existence — a 0.3% line computes to a
 * sub-pixel width and vanishes, which reads exactly like not holding the asset
 * at all. Every present segment keeps at least 2px.
 *
 * There is no gap between segments. A gutter would push the row past 100% and
 * flex would shrink every width to fit, which is a small lie about a
 * proportion. The colours do the separating.
 *
 * A fund TEFAS published nothing for gets a flat rule rather than a bar. A
 * full-width "other" segment would invent a composition out of missing data.
 *
 * Two things are new. The label: twelve `title` attributes are invisible to a
 * screen reader, so the whole composition is read out once from the bar itself.
 *
 * And the two directions a TEFAS row can miss 100% are handled differently,
 * because they mean different things. Under, the gap is information — the fund
 * reported less than all of itself — so the tail stays as bare track. Over,
 * which is ordinary for a leveraged or short-carrying fund (TLY reports 107.6%),
 * there is no room to show it: the widths are scaled to fit and the reported
 * total is printed instead. Letting it overflow would clip the last segments,
 * which is the one outcome that would misstate the holding rather than the sum.
 */
export default function FundAllocationBar({
  segments,
  total,
  height = 'thin',
  showLegend = false,
  className = '',
}: FundAllocationBarProps) {
  const track = height === 'wide' ? 'h-3' : 'h-1.5';
  const scale = total > 1 ? 1 / total : 1;
  const misreported = Math.abs(total - 1) > 0.005;

  if (segments.length === 0) {
    return (
      <div
        className={`${track} w-full rounded-sm bg-surface-2 ${className}`}
        title="TEFAS bu fon için portföy dağılımı yayımlamıyor"
      />
    );
  }

  const summary = allocationSummary(segments);

  return (
    <div className={className}>
      <div
        className={`flex ${track} w-full overflow-hidden rounded-sm bg-surface-2`}
        role="img"
        aria-label={summary}
        title={summary}
      >
        {segments.map((segment) => (
          <div
            key={segment.key}
            className="shrink-0"
            style={{
              width: `${segment.weight * scale * 100}%`,
              minWidth: '2px',
              // A bucket's colour is fixed data rather than a utility class:
              // two of the twelve are `color-mix` expressions Tailwind would
              // have to generate, and all twelve have to stay identical across
              // every bar for two funds to be comparable.
              backgroundColor: segment.color,
            }}
          />
        ))}
      </div>

      {showLegend && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          {segments.map((segment) => (
            <span key={segment.key} className="flex items-center gap-1.5 text-2xs text-fg-muted">
              {/* A swatch beside a muted label, rather than the coloured label
                  the ownership bar uses. That palette is uniformly bright; two
                  of these twelve are deliberately dimmed siblings and would
                  fail contrast as text. */}
              <span
                className="h-2 w-2 shrink-0 rounded-sm"
                style={{ backgroundColor: segment.color }}
                aria-hidden
              />
              <span className="truncate">{segment.label}</span>
              <span className="tabnum text-fg">{formatWeight(segment.weight)}</span>
            </span>
          ))}
          {misreported && (
            <span className="text-2xs text-fg-subtle">TEFAS toplamı {formatPercent(total)}</span>
          )}
        </div>
      )}
    </div>
  );
}
