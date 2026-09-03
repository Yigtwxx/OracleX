'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMarketOverview, useFearGreedIndex, useNasdaqOverview } from '@/hooks/queries';
import { FearGreedData, MarketOverview } from '@/lib/api';
import { HistogramBucket } from '@/lib/market-breadth';
import FearGreedGauge from './FearGreedGauge';
import { TrendingUp, TrendingDown, Activity, Flame } from 'lucide-react';
import MarketStatsBar from './overview/MarketStatsBar';
import AssetListCard from './overview/AssetListCard';
import AssetTable from './overview/AssetTable';
import MarketBreadthStrip from './overview/MarketBreadthStrip';
import ChangeDistribution from './overview/ChangeDistribution';
import DivergenceBoard from './overview/DivergenceBoard';

export default function OverviewPage({
  marketType = 'crypto',
}: {
  marketType?: 'crypto' | 'nasdaq';
}) {
  const isCrypto = marketType === 'crypto';

  // The distribution chart draws the selection but the table applies it, so the
  // page holds it. Kept here rather than in the chart so switching markets can
  // drop a bucket that means nothing in the other one.
  const [changeFilter, setChangeFilter] = useState<HistogramBucket | null>(null);
  const tableRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setChangeFilter(null);
  }, [marketType]);

  // Use the appropriate hooks based on market type
  const cryptoMarket = useMarketOverview(isCrypto);
  const fearGreed = useFearGreedIndex(isCrypto);
  const nasdaq = useNasdaqOverview(!isCrypto);
  // Not gated on market type: the Pentagon reading is about attention, and it
  // says the same thing whether the page is showing crypto or equities.

  // Derive the active data based on market type
  const marketData = isCrypto
    ? (cryptoMarket.data ?? null)
    : ((nasdaq.data as MarketOverview | undefined) ?? null);
  const isLoading = isCrypto ? cryptoMarket.isLoading || fearGreed.isLoading : nasdaq.isLoading;
  const isFetching = isCrypto ? cryptoMarket.isFetching || fearGreed.isFetching : nasdaq.isFetching;

  // Build fearGreedData from the correct source
  const fearGreedData: FearGreedData | null = useMemo(() => {
    if (isCrypto) {
      return fearGreed.data ?? null;
    }
    // For NASDAQ, extract from the nasdaq response
    const nasdaqFg = nasdaq.data?.fear_greed;
    if (nasdaqFg) {
      return {
        value: nasdaqFg.value,
        classification: nasdaqFg.classification,
        timestamp: nasdaqFg.timestamp,
        history: [],
      };
    }
    return null;
  }, [isCrypto, fearGreed.data, nasdaq.data]);

  const lastUpdate = isCrypto
    ? cryptoMarket.dataUpdatedAt > 0
      ? new Date(cryptoMarket.dataUpdatedAt)
      : null
    : nasdaq.dataUpdatedAt > 0
      ? new Date(nasdaq.dataUpdatedAt)
      : null;

  // The chart sits below the table it filters, so selecting a bucket without
  // moving the viewport narrows a list the user cannot see. Scrolling back to
  // the table is what makes the two read as one control.
  const handleBucketSelect = (bucket: HistogramBucket | null) => {
    setChangeFilter(bucket);
    if (bucket) {
      tableRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const handleRefresh = () => {
    if (isCrypto) {
      cryptoMarket.refetch();
      fearGreed.refetch();
    } else {
      nasdaq.refetch();
    }
  };

  // Derived data for trending, gainers, losers.
  //
  // The tail of a 250-asset list is thin: assets that barely trade post the
  // wildest percentage moves, so an unfiltered ranking surfaces names nobody
  // can act on. Only assets with real turnover are eligible — and if the
  // filter would empty the list (a quiet market, a partial payload), the
  // unfiltered set is ranked instead.
  const { topGainers, topLosers } = useMemo(() => {
    if (!marketData?.coins?.length) return { topGainers: [], topLosers: [] };

    const MIN_VOLUME_24H = 1_000_000;
    const liquid = marketData.coins.filter((coin) => coin.volume_24h >= MIN_VOLUME_24H);
    const pool = liquid.length >= 6 ? liquid : marketData.coins;

    const sorted = [...pool].sort((a, b) => b.change_24h - a.change_24h);
    return {
      topGainers: sorted.slice(0, 3),
      topLosers: sorted.slice(-3).reverse(),
    };
  }, [marketData]);

  return (
    <div className="h-full overflow-y-auto custom-scrollbar">
      {/* ===== TOP MARKET STATS BAR ===== */}
      <MarketStatsBar
        marketData={marketData}
        fearGreedData={fearGreedData}
        marketType={marketType}
        isLoading={isLoading}
        lastUpdate={lastUpdate}
        onRefresh={handleRefresh}
      />

      <div className="max-w-[1800px] mx-auto px-4 py-4 space-y-4">
        {/* ===== TRENDING / GAINERS / LOSERS CARDS ===== */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-3">
          {/* Fear & Greed Card */}
          <div className="lg:col-span-1 surface p-4">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-3.5 h-3.5 text-fg-muted" />
              <h3 className="label">Fear &amp; Greed Index</h3>
            </div>
            <FearGreedGauge data={fearGreedData} isLoading={isLoading} size="sm" />
          </div>

          <AssetListCard
            title="Trending"
            icon={Flame}
            data={marketData?.coins.slice(0, 3) || []}
            isLoading={isLoading}
            marketType={marketType}
            type="trending"
          />

          <AssetListCard
            title="Top Gainers"
            icon={TrendingUp}
            data={topGainers}
            isLoading={isLoading}
            marketType={marketType}
            type="gainer"
          />

          <AssetListCard
            title="Top Losers"
            icon={TrendingDown}
            data={topLosers}
            isLoading={isLoading}
            marketType={marketType}
            type="loser"
          />
        </div>

        {/* ===== ASSET TABLE ===== */}
        {/* `scroll-mt` clears the sticky stats bar. Without it, scrolling the
            table into view parks its header — and the filter chip that explains
            why the list is short — underneath that bar. */}
        <div ref={tableRef} className="scroll-mt-14">
          <AssetTable
            marketData={marketData}
            marketType={marketType}
            isLoading={isLoading}
            changeFilter={changeFilter}
            onClearChangeFilter={() => setChangeFilter(null)}
          />
        </div>

        {/* ===== MARKET INTERNALS =====
            Three readings the totals in the stats bar cannot give: how many
            moved, how the moves are spread, and which names contradict their
            own week. All derived from the payload the table above already
            renders. */}
        <MarketBreadthStrip marketData={marketData} marketType={marketType} isLoading={isLoading} />

        <ChangeDistribution
          marketData={marketData}
          marketType={marketType}
          isLoading={isLoading}
          selected={changeFilter}
          onSelect={handleBucketSelect}
        />

        <DivergenceBoard marketData={marketData} marketType={marketType} isLoading={isLoading} />
      </div>
    </div>
  );
}
