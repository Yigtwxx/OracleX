import type { ChartStructure } from '@/store/useStore';
import { formatLevel, formatSignedPercent, rangeFraction } from '@/lib/technical-format';

/**
 * The view from a distance: where this price sits in its own multi-year range.
 *
 * The one thing a levels table cannot say. A band 3% overhead means something
 * different when price is at 16% of its two-year range than at 78% of it, and
 * that difference is the first thing a reader should see — hence its place
 * above the ladder rather than below it.
 *
 * Renders nothing without a range. A bar with an arbitrarily placed marker
 * reads as a measurement, and the midpoint is itself a claim.
 */
export default function RangeStrip({
  structure,
  price,
}: {
  structure: ChartStructure;
  price?: number | null;
}) {
  const fraction = rangeFraction(price, structure.range_low, structure.range_high);
  const facts = [
    structure.range_bars && structure.range_timeframe
      ? `${structure.range_bars} ${structure.range_timeframe} bars`
      : null,
    typeof structure.distance_to_high_percent === 'number'
      ? `${formatSignedPercent(structure.distance_to_high_percent)} from the high`
      : null,
    typeof structure.price_vs_sma200_percent === 'number'
      ? `${formatSignedPercent(structure.price_vs_sma200_percent)} vs the 200-bar SMA`
      : null,
    structure.swing_structure,
  ].filter(Boolean) as string[];

  if (fraction === null && !facts.length) return null;

  return (
    <div>
      {fraction !== null && (
        <>
          <div className="relative h-1 rounded-full bg-surface-2" aria-hidden="true">
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-line-strong"
              style={{ width: `${fraction * 100}%` }}
            />
            <div
              className="absolute top-1/2 -mt-[3px] -ml-[3px] h-1.5 w-1.5 rounded-full bg-fg"
              style={{ left: `${fraction * 100}%` }}
            />
          </div>
          <div className="mt-1 flex items-center justify-between text-2xs tabnum text-fg-subtle">
            <span>{formatLevel(structure.range_low as number)}</span>
            <span className="text-fg-muted">
              {(fraction * 100).toFixed(0)}% of range
              {structure.range_timeframe ? ` · ${structure.range_timeframe}` : ''}
            </span>
            <span>{formatLevel(structure.range_high as number)}</span>
          </div>
        </>
      )}

      {facts.length > 0 && (
        <p className="mt-1.5 text-sm leading-relaxed text-fg-muted">{facts.join(' · ')}</p>
      )}
    </div>
  );
}
