'use client';

import { MacroQuote } from '@/lib/api';
import SparklineChart from '@/components/overview/SparklineChart';
import Delta from './Delta';
import RangeBar from './RangeBar';
import { UNKNOWN, formatPrice } from './format';
import { metalBarClasses, metalClass } from './metals';

interface HeroCardProps {
  quote: MacroQuote | undefined;
  /** Overrides the server name where a shorter one reads better at this size. */
  label?: string;
  unit?: string;
}

/**
 * A headline instrument, given the space to show its week as well as its price.
 *
 * The four of these across the top are the ones a macro reader checks first;
 * everything else on the page is a table row. The sparkline is drawn from the
 * same series the 7-day figure is computed from, so the line and the number
 * cannot disagree.
 */
export default function HeroCard({ quote, label, unit }: HeroCardProps) {
  if (!quote) return <div className="surface h-[140px] shimmer" />;

  const hasPrice = quote.price !== null;
  const hasLine = quote.sparkline.length > 1;
  // The line takes its colour from the week, not the day: it is drawing seven
  // days, and tinting it by the 24h move would label the wrong span.
  const weekIsUp = (quote.change_7d ?? 0) >= 0;

  return (
    <div className="surface p-4 flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        {/* `label` inherits the metal hue; the fallback keeps the muted eyebrow
            colour, so a non-metal hero is not left with an unstyled heading. */}
        <span className={`label truncate ${metalClass(quote.symbol, 'text-fg-muted')}`}>
          {label ?? quote.name}
        </span>
        {unit && <span className="text-2xs text-fg-subtle shrink-0">{unit}</span>}
      </div>

      <div className="flex items-baseline gap-2 flex-wrap">
        <span className={`text-xl font-mono tabnum ${hasPrice ? 'text-fg' : 'text-fg-subtle'}`}>
          {hasPrice ? formatPrice(quote.price as number) : UNKNOWN}
        </span>
        <Delta value={quote.change_24h} className="text-sm" />
      </div>

      <div className="flex items-end justify-between gap-3">
        <div className="text-2xs text-fg-subtle">
          7d{' '}
          {quote.change_7d === null ? (
            <span className="font-mono tabnum">{UNKNOWN}</span>
          ) : (
            <Delta value={quote.change_7d} className="text-2xs" />
          )}
        </div>
        {/* A single point is not a line; the slot collapses rather than drawing
            a flat stub that would read as a week of no movement. */}
        {hasLine && (
          <div className="shrink-0">
            <SparklineChart data={quote.sparkline} positive={weekIsUp} />
          </div>
        )}
      </div>

      <RangeBar
        price={quote.price}
        low={quote.low_52w}
        high={quote.high_52w}
        variant="full"
        accent={metalBarClasses(quote.symbol)}
      />
    </div>
  );
}
