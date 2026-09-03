'use client';

import { useMemo } from 'react';
import { X } from 'lucide-react';
import { MarketOverview } from '@/lib/api';
import { HistogramBucket, changeHistogram } from '@/lib/market-breadth';

interface ChangeDistributionProps {
  marketData: MarketOverview | null;
  marketType: 'crypto' | 'nasdaq';
  isLoading: boolean;
  /** The bucket the table is currently filtered to, if any. */
  selected: HistogramBucket | null;
  /** Passing `null` clears the filter. */
  onSelect: (bucket: HistogramBucket | null) => void;
}

/**
 * Colour is direction and nothing else.
 *
 * The two buckets either side of zero were drawn dimmed at first, on the theory
 * that "barely moved" should not read as a direction. On a normal day those are
 * also the tallest bars, so dimming turned the centre of the chart into two
 * dark slabs and buried exactly where the market is. The zero line below does
 * that job instead, without touching the bars.
 */
const barStyle = (bucket: HistogramBucket): React.CSSProperties => ({
  background: bucket.min < 0 ? 'var(--down)' : 'var(--up)',
});

function Skeleton() {
  return (
    <div className="surface p-4 space-y-3">
      <div className="h-2.5 w-40 rounded bg-surface-2 shimmer" />
      <div className="h-28 w-full rounded bg-surface-2 shimmer" />
    </div>
  );
}

/**
 * The shape of the day: how the 24h moves are spread across the universe.
 *
 * It is also the table's filter. A summary nobody can act on gets read once and
 * then ignored, so clicking a column narrows the table above to exactly the
 * assets that column counts — the chart answers "how many are down 3–6%?" and
 * then hands over the list.
 */
export default function ChangeDistribution({
  marketData,
  marketType,
  isLoading,
  selected,
  onSelect,
}: ChangeDistributionProps) {
  const buckets = useMemo(
    () => (marketData?.coins?.length ? changeHistogram(marketData.coins) : []),
    [marketData]
  );

  if (isLoading && buckets.length === 0) return <Skeleton />;
  if (buckets.length === 0) return null;

  const counted = buckets.reduce((sum, b) => sum + b.count, 0);
  if (counted === 0) return null;

  const tallest = Math.max(...buckets.map((b) => b.count));
  const noun = marketType === 'nasdaq' ? 'stocks' : 'assets';

  const isSelected = (bucket: HistogramBucket) =>
    selected != null && selected.min === bucket.min && selected.max === bucket.max;

  return (
    <div className="surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="label">24h change distribution</h3>
        <span className="text-2xs font-mono tabnum text-fg-subtle">
          {counted} {noun}
        </span>
      </div>

      {/* Twelve columns do not fit a phone. The chart scrolls inside its own
          box rather than squeezing the labels into illegibility. */}
      <div className="mt-3 overflow-x-auto custom-scrollbar">
        <div className="min-w-[560px]">
          {/* Twelve equal columns, six of them below zero, so the boundary is
              the exact middle of the row. */}
          <div className="relative flex items-end gap-1.5 h-32">
            <span
              aria-hidden
              className="absolute inset-y-0 left-1/2 w-px bg-line-strong pointer-events-none"
            />
            {buckets.map((bucket) => {
              const active = isSelected(bucket);
              return (
                <button
                  key={bucket.label}
                  type="button"
                  onClick={() => onSelect(active ? null : bucket)}
                  aria-pressed={active}
                  aria-label={`${bucket.count} ${noun} changed ${bucket.label}`}
                  title={`${bucket.count} ${noun}`}
                  className="flex-1 h-full flex flex-col justify-end items-center gap-1 group focus-visible:outline-none"
                >
                  <span
                    className={`text-2xs font-mono tabnum transition-colors ${
                      active ? 'text-fg' : 'text-fg-subtle group-hover:text-fg-muted'
                    }`}
                  >
                    {bucket.count || ''}
                  </span>
                  <span
                    className={`w-full rounded-t-sm transition-all group-hover:brightness-125 ${
                      active ? 'ring-1 ring-fg ring-offset-1 ring-offset-surface' : ''
                    } group-focus-visible:ring-1 group-focus-visible:ring-accent`}
                    style={{
                      ...barStyle(bucket),
                      // A zero-count bucket still needs a hit target, so it
                      // keeps a hairline rather than collapsing to nothing.
                      height: bucket.count
                        ? `${Math.max(2, (bucket.count / tallest) * 100)}%`
                        : '2px',
                    }}
                  />
                </button>
              );
            })}
          </div>

          <div className="mt-1.5 pt-1.5 border-t border-line flex gap-1.5">
            {buckets.map((bucket) => (
              <span
                key={bucket.label}
                className={`flex-1 text-center text-2xs font-mono tabnum ${
                  isSelected(bucket) ? 'text-fg' : 'text-fg-subtle'
                }`}
              >
                {bucket.label}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2 min-h-[26px]">
        {selected ? (
          <>
            <button
              type="button"
              onClick={() => onSelect(null)}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-accent-bg border border-accent/40 text-2xs font-mono tabnum text-fg hover:border-accent transition-colors"
            >
              {selected.label}
              <X className="w-3 h-3" aria-hidden />
              <span className="sr-only">Clear distribution filter</span>
            </button>
            <span className="text-sm text-fg-muted">table filtered to this range</span>
          </>
        ) : (
          <span className="text-sm text-fg-subtle">Select a column to filter the table above.</span>
        )}
      </div>
    </div>
  );
}
