'use client';

import { formatNumber, formatPercent } from '@/lib/bist-format';
import type { RangeBucket } from '@/lib/bist-positioning';

interface RangeDistributionProps {
  buckets: RangeBucket[];
  selected?: number;
  onSelect: (index: number | undefined) => void;
  height?: number;
}

/**
 * Where the board sits inside its own year.
 *
 * DOM rather than a chart library, for the same reason the treemaps in this
 * codebase are: twenty bars that each need to be a focusable, pressable control
 * are cheaper and more accurate as twenty elements than as a canvas with a
 * hit-test bolted on.
 *
 * Height is the count and colour is the median RSI, which is the pairing the
 * panel exists for. A tall bar near the high is a market that has run; a tall
 * bar near the high whose RSI has slipped under fifty is a market that has run
 * and stopped being bought, and neither number says that on its own. RSI is
 * signed around fifty, so it takes the up/down pair rather than a sequential
 * ramp — on a sequential ramp mildly overbought and mildly oversold would sit
 * next to each other as though they were the same reading.
 */
export default function RangeDistribution({
  buckets,
  selected,
  onSelect,
  height = 200,
}: RangeDistributionProps) {
  const tallest = buckets.reduce((max, bucket) => Math.max(max, bucket.count), 0);
  const total = buckets.reduce((sum, bucket) => sum + bucket.count, 0);

  if (total === 0) {
    return (
      <p
        style={{ height }}
        className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
      >
        52 haftalık aralığı ölçülebilen hisse yok.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-3">
      <p className="sr-only">
        {total} hissenin 52 haftalık aralıktaki konumu, dipten zirveye yirmi dilimde.
      </p>

      <div className="flex items-end gap-px" style={{ height }}>
        {buckets.map((bucket) => {
          const share = tallest > 0 ? bucket.count / tallest : 0;
          const active = selected === bucket.index;
          const label = `${formatPercent(bucket.from, 0)}–${formatPercent(bucket.to, 0)} aralığında ${bucket.count} hisse${
            bucket.medianRsi === null ? '' : `, medyan RSI ${formatNumber(bucket.medianRsi, 0)}`
          }`;

          return (
            <button
              key={bucket.index}
              type="button"
              disabled={bucket.count === 0}
              aria-pressed={active}
              aria-label={label}
              title={label}
              onClick={() => onSelect(active ? undefined : bucket.index)}
              className="group flex h-full flex-1 flex-col justify-end disabled:cursor-default"
            >
              <span
                className={`w-full rounded-sm transition-opacity ${
                  active ? 'opacity-100' : 'opacity-80 group-enabled:group-hover:opacity-100'
                }`}
                style={{
                  // A bar with a count must never round to nothing: a single
                  // name at the year's high is exactly the reading this panel is
                  // for, and a 0.4px bar would hide it.
                  height: bucket.count === 0 ? 1 : `${Math.max(3, share * 100)}%`,
                  background: fillFor(bucket),
                  outline: active ? '1px solid var(--fg)' : undefined,
                }}
              />
            </button>
          );
        })}
      </div>

      <div className="flex items-center justify-between text-2xs text-fg-subtle">
        <span>yıllık dip</span>
        <span className="text-fg-muted">RSI: kırmızı &lt;50 · yeşil &gt;50</span>
        <span>yıllık zirve</span>
      </div>
    </div>
  );
}

/** Median RSI as a tint, neutral at fifty and saturating by twenty-five points either way. */
function fillFor(bucket: RangeBucket): string {
  if (bucket.count === 0) return 'var(--border)';
  if (bucket.medianRsi === null) return 'var(--surface-2)';
  const distance = Math.min(1, Math.abs(bucket.medianRsi - 50) / 25);
  const strength = Math.round((0.25 + distance * 0.6) * 100);
  const token = bucket.medianRsi >= 50 ? 'var(--up)' : 'var(--down)';
  return `color-mix(in srgb, ${token} ${strength}%, transparent)`;
}
