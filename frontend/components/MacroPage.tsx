'use client';

import { RefreshCw } from 'lucide-react';
import { useMacroBoard, useMacroRegime } from '@/hooks/queries';
import { MacroQuote } from '@/lib/api';
import CommodityPanel from './macro/CommodityPanel';
import HeroCard from './macro/HeroCard';
import IndexPanel from './macro/IndexPanel';
import MacroRatios from './macro/MacroRatios';
import RegimeCard from './macro/RegimeCard';

/**
 * The four instruments across the top, and the short names they wear there.
 *
 * A fixed list rather than "the first four rows": these are the ones a macro
 * reader checks before anything else, and a board that reordered itself by
 * whatever moved most would make the page unreadable at a glance.
 */
const HERO: { symbol: string; label: string }[] = [
  { symbol: 'GC=F', label: 'Gold' },
  { symbol: 'SI=F', label: 'Silver' },
  { symbol: 'CL=F', label: 'WTI Crude' },
  { symbol: 'DX-Y.NYB', label: 'Dollar Index' },
];

export default function MacroPage() {
  const board = useMacroBoard();
  const regime = useMacroRegime();

  const quotes = new Map<string, MacroQuote>();
  for (const row of board.data?.commodities ?? []) quotes.set(row.symbol, row);
  for (const row of board.data?.indices ?? []) quotes.set(row.symbol, row);

  const unitFor = (symbol: string) =>
    board.data?.commodities.find((row) => row.symbol === symbol)?.unit;

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="max-w-[1600px] mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-fg">Macro</h1>
            <p className="text-base text-fg-muted">
              Commodity futures, benchmark indices and the dollar.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {/* The server's own `as_of`, not the client's fetch time — a cached
                payload replayed after an upstream failure must not be stamped
                with the moment the browser asked for it. */}
            {board.data?.as_of && (
              <span className="flex items-center gap-2">
                {board.data.stale && (
                  <span
                    title="Upstream unavailable — showing the last known board"
                    className="px-1.5 py-0.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle"
                  >
                    Stale
                  </span>
                )}
                <span className="text-xs font-mono tabnum text-fg-subtle">
                  {new Date(board.data.as_of).toLocaleTimeString('en-GB')}
                </span>
              </span>
            )}
            <button
              onClick={() => board.refetch()}
              aria-label="Refresh macro board"
              className="p-1.5 bg-surface border border-line rounded-md text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${board.isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* A failed board is reported, not rendered as an empty page: blank
            panels would read as "gold, oil and the S&P 500 have nothing to
            report", which is a claim nothing here can make. */}
        {board.isError ? (
          <div className="surface p-6 text-center">
            <p className="text-base text-fg">The macro board is unavailable.</p>
            <p className="mt-1 text-sm text-fg-subtle">
              The upstream quote feeds could not be reached.
            </p>
            <button
              onClick={() => board.refetch()}
              className="mt-3 px-3 py-1.5 bg-surface-2 border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              Try again
            </button>
          </div>
        ) : (
          <>
            {/* The page's one-line answer, above the instruments it was read
                from. Absent entirely when too many feeds were missing to score
                it — the board below already reports what went wrong. */}
            <RegimeCard regime={regime.data} isLoading={regime.isLoading} />

            {/* Top Row: headline instruments */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {HERO.map(({ symbol, label }) => (
                <HeroCard
                  key={symbol}
                  quote={board.isLoading ? undefined : quotes.get(symbol)}
                  label={label}
                  unit={unitFor(symbol)}
                />
              ))}
            </div>

            {/* Second Row: ratios derived from the prices above */}
            <MacroRatios ratios={board.data?.ratios ?? []} />

            {/* Bottom Row: the full board */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 h-[560px]">
              <CommodityPanel rows={board.data?.commodities ?? []} isLoading={board.isLoading} />
              <IndexPanel rows={board.data?.indices ?? []} isLoading={board.isLoading} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
