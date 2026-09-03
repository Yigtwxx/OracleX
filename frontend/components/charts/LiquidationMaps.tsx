'use client';

import { useState } from 'react';
import { Info, RefreshCw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';

import { LIQUIDATION_SYMBOLS, type LiquidationVenue } from '@/lib/api';
import LiquidationProfile from './LiquidationProfile';

/**
 * Every venue's liquidation book, and what they come to together.
 *
 * A liquidation book belongs to an exchange. Positions on OKX are liquidated by
 * OKX's price against OKX's open interest, and the map that results says
 * nothing about what is stacked on Binance. Where the venues agree is a level
 * the whole market has to trade through; where only one has a wall, the cascade
 * is local and stops there.
 *
 * Each pane is fetched from its own venue's public statistics — nothing is
 * inferred from one exchange and relabelled as another. The aggregate is last
 * because it is the sum of what is above it, and it names only the venues that
 * actually answered, so a feed going down shortens the label rather than
 * quietly shrinking the market.
 *
 * Hyperliquid, which the reference terminal shows, is missing on purpose: it
 * publishes neither an open-interest history nor an account long/short ratio,
 * so its book could only be modelled from volume with a neutral split. That is
 * the degraded path the others fall back to when their statistics run out, and
 * dressing it up as a peer would be the least honest thing on the page.
 */

/**
 * The books worth a pane of their own, then the sum of every book there is.
 *
 * Bybit is in the aggregate but has no pane. It is modelled the same way and
 * the endpoint will serve it — it is left off because three charts is what
 * fits, and the two largest venues plus the total is the comparison people
 * actually make. The aggregate names every venue in it, so nothing is hidden:
 * the label reads "Binance + OKX + Bybit" and the sum is checkable against the
 * two panes above it.
 */
const PANES: { venue: LiquidationVenue; label: string }[] = [
  { venue: 'binance', label: 'Binance' },
  { venue: 'okx', label: 'OKX' },
  { venue: 'all', label: 'All venues' },
];

/**
 * How much history feeds the book, named by the window rather than by the
 * candle interval.
 *
 * The other two views on this page expose the interval because it decides what
 * they resolve. Here it decides nothing visible — there is no time axis — and
 * only the span matters: it is how far back a level can have been opened and
 * still be standing. One control drives all three panes, because two panes on
 * different windows are not comparable and comparing them is the point.
 *
 * The pairs deliberately do not share an interval. At 12H a one-hour bar would
 * leave twelve columns to build a book out of; at 1W a five-minute one would
 * need six times the candles either exchange serves in a page.
 */
const WINDOWS = [
  { label: '12H', interval: '5m', columns: 144 },
  { label: '1D', interval: '15m', columns: 96 },
  { label: '1W', interval: '1h', columns: 168 },
] as const;

type WindowLabel = (typeof WINDOWS)[number]['label'];

interface LiquidationMapsProps {
  className?: string;
}

export default function LiquidationMaps({ className = '' }: LiquidationMapsProps) {
  const [symbol, setSymbol] = useState<string>(LIQUIDATION_SYMBOLS[0]);
  const [range, setRange] = useState<WindowLabel>('1D');
  const queryClient = useQueryClient();

  const active = WINDOWS.find((entry) => entry.label === range) ?? WINDOWS[1];

  // One button for all three panes: they are read against each other, and
  // refreshing them one at a time would compare a book to an older book.
  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ['liquidationProfile'] });
  };

  return (
    <div className={`flex flex-col w-full h-full bg-bg ${className}`}>
      {/* Toolbar */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-3 h-10 border-b border-line bg-surface overflow-x-auto">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base font-semibold text-fg truncate">Liquidation Map</span>

          <select
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            aria-label="Market"
            className="px-1.5 py-0.5 rounded text-2xs font-mono bg-surface-2 text-fg-muted border border-line hover:text-fg"
          >
            {LIQUIDATION_SYMBOLS.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </select>

          <span
            className="text-fg-subtle"
            title="Estimated liquidation levels modelled from each venue's own open interest, volume and long/short ratio — not observed liquidations. Bars are the book standing at each price; the curves are those bars accumulated outward from spot."
          >
            <Info className="w-3 h-3" />
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <div className="flex gap-0.5" role="group" aria-label="History window">
            {WINDOWS.map(({ label }) => (
              <button
                key={label}
                onClick={() => setRange(label)}
                title={`Levels opened over the last ${label}`}
                className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                  range === label ? 'bg-surface-2 text-fg' : 'text-fg-subtle hover:text-fg-muted'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <button
            onClick={refreshAll}
            title="Refresh every pane"
            className="p-1 rounded border border-line text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Panes — tall enough that a bar's tier stack is readable, which puts
          the last one below the fold. That is the right trade: a third of a
          viewport each would make all three unreadable to save a scroll.

          Snapped to pane boundaries, though, because the cost of not doing it
          is a misreading rather than an inconvenience. These bars stand on a
          zero baseline and grow upward, so a scroll position halfway down a
          pane hides that baseline and leaves only the tops of the tallest bars
          on screen — which reads as a venue with almost no book at all. It is
          convincing enough that it fooled the person who wrote this into
          reporting OKX as a data problem. Snapping makes a half-pane view
          unreachable. */}
      <div className="flex-1 min-h-0 overflow-y-auto snap-y snap-mandatory">
        {PANES.map(({ venue, label }, index) => (
          <LiquidationProfile
            key={venue}
            symbol={symbol}
            venue={venue}
            label={label}
            interval={active.interval}
            columns={active.columns}
            showLegend={index === 0}
            className={`h-[420px] snap-start ${index > 0 ? 'border-t border-line' : ''}`}
          />
        ))}
      </div>
    </div>
  );
}
