'use client';

import {
  useFearGreedIndex,
  useFundingRates,
  useLiquidations,
  useMacroCalendar,
  useMarketOverview,
} from '@/hooks/queries';
import AssetBrief from './home/AssetBrief';
import MarketRibbon from './home/MarketRibbon';
import FundingRates from './home/FundingRates';
import LiquidationFeed from './home/LiquidationFeed';
import MacroCalendar from './home/MacroCalendar';
import WatchlistWidget from './home/WatchlistWidget';
import { RefreshCw } from 'lucide-react';

export default function HomePage() {
  const market = useMarketOverview();
  const fearGreed = useFearGreedIndex();
  const funding = useFundingRates();
  const liquidations = useLiquidations();
  const macro = useMacroCalendar();

  // Each widget tracks its own query — one slow source must not blank the page.
  // The brief's queries are deliberately absent: they live per card so a symbol
  // swap does not spin this button on behalf of two assets that did not change.
  const isFetching =
    market.isFetching ||
    fearGreed.isFetching ||
    funding.isFetching ||
    liquidations.isFetching ||
    macro.isFetching;

  const handleRefresh = () => {
    market.refetch();
    fearGreed.refetch();
    funding.refetch();
    liquidations.refetch();
    macro.refetch();
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="max-w-[1600px] mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-fg">Market Intelligence</h1>
            <div className="mt-1">
              <MarketRibbon
                marketData={market.data ?? null}
                fearGreedData={fearGreed.data ?? null}
                isLoading={market.isLoading}
              />
            </div>
          </div>
          <div className="flex items-center gap-3 shrink-0">
            {/* The server's own timestamp, not the client's fetch time — a cached
                payload replayed after an upstream failure used to be stamped with
                the moment the browser asked for it. */}
            {market.data?.timestamp && (
              <span className="text-xs font-mono tabnum text-fg-subtle">
                {new Date(market.data.timestamp).toLocaleTimeString('en-GB')}
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

        {/* Top Row: the reader's own assets */}
        <AssetBrief />

        {/* Middle Row: 3-Column Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:h-[480px]">
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
