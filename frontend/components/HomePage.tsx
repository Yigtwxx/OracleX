'use client';

import {
  useOnChainData,
  useFundingRates,
  useLiquidations,
  useMacroCalendar,
} from '@/hooks/queries';
import OnChainStats from './home/OnChainStats';
import FundingRates from './home/FundingRates';
import LiquidationFeed from './home/LiquidationFeed';
import MacroCalendar from './home/MacroCalendar';
import WatchlistWidget from './home/WatchlistWidget';
import { RefreshCw } from 'lucide-react';

export default function HomePage() {
  const onChain = useOnChainData();
  const funding = useFundingRates();
  const liquidations = useLiquidations();
  const macro = useMacroCalendar();

  // Each widget tracks its own query — one slow source must not blank the page.
  const isFetching =
    onChain.isFetching || funding.isFetching || liquidations.isFetching || macro.isFetching;

  const handleRefresh = () => {
    onChain.refetch();
    funding.refetch();
    liquidations.refetch();
    macro.refetch();
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="max-w-[1600px] mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-fg">Market Intelligence</h1>
            <p className="text-base text-fg-muted">
              Real-time on-chain data, funding rates, and macroeconomic events.
            </p>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {/* The server's own `as_of`, not the client's fetch time — a cached
                payload replayed after an upstream failure used to be stamped with
                the moment the browser asked for it. */}
            {onChain.data?.as_of && (
              <span className="flex items-center gap-2">
                {onChain.data.stale && (
                  <span
                    title="Upstream unavailable — showing the last known values"
                    className="px-1.5 py-0.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle"
                  >
                    Stale
                  </span>
                )}
                <span className="text-xs font-mono tabnum text-fg-subtle">
                  {new Date(onChain.data.as_of).toLocaleTimeString('en-GB')}
                </span>
              </span>
            )}
            <button
              onClick={handleRefresh}
              aria-label="Refresh dashboard data"
              className="p-1.5 bg-surface border border-line rounded-md text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Top Row: On-Chain Stats */}
        <OnChainStats data={onChain.data ?? null} isLoading={onChain.isLoading} />

        {/* Middle Row: 3-Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 h-[480px]">
          {/* Col 1: Funding Rates */}
          <FundingRates data={funding.data ?? []} isLoading={funding.isLoading} />

          {/* Col 2: Liquidations */}
          <LiquidationFeed data={liquidations.data ?? []} isLoading={liquidations.isLoading} />

          {/* Col 3: Macro Calendar */}
          <MacroCalendar
            data={macro.data ?? []}
            isLoading={macro.isLoading}
            isError={macro.isError}
          />
        </div>

        {/* Bottom Row: Watchlist */}
        <WatchlistWidget />
      </div>
    </div>
  );
}
