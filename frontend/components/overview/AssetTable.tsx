'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowUp, ArrowDown, ChevronLeft, ChevronRight, Wifi, WifiOff } from 'lucide-react';
import { MarketOverview } from '@/lib/api';
import SparklineChart from './SparklineChart';
import { useWebSocketPrices } from '@/hooks/useWebSocketPrices';
import AssetDetailModal from './AssetDetailModal';
import { getAssetLogo, getAssetName, formatPrice, formatVolume } from './overview-utils';

interface AssetTableProps {
  marketData: MarketOverview | null;
  marketType: 'crypto' | 'nasdaq';
  isLoading: boolean;
}

const GRID = 'grid grid-cols-[40px_1fr_120px_100px_100px_130px_130px_110px] gap-2 px-4';

// The API returns 250 rows. Rendering them all at once means 250 inline SVG
// sparklines on first paint, so the table pages instead.
const PAGE_SIZE = 50;

export default function AssetTable({ marketData, marketType, isLoading }: AssetTableProps) {
  const [selectedAsset, setSelectedAsset] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);

  // WebSocket for real-time crypto prices
  const { prices: wsPrices, isConnected } = useWebSocketPrices({
    enabled: marketType === 'crypto',
  });

  const getRealTimePrice = (symbol: string) => {
    if (marketType !== 'crypto') return undefined;
    const normalizedSymbol = symbol.replace('USDT', '').replace('/', '').toUpperCase();
    return wsPrices[normalizedSymbol];
  };

  const coins = useMemo(() => marketData?.coins ?? [], [marketData]);
  const totalPages = Math.max(1, Math.ceil(coins.length / PAGE_SIZE));

  // Switching between crypto and stocks swaps the whole list out from under
  // whatever page the user was on.
  useEffect(() => {
    setPage(1);
  }, [marketType]);

  // A refresh can shrink the list; never strand the user past the last page.
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const visibleCoins = coins.slice(pageStart, pageStart + PAGE_SIZE);

  const rangeLabel = coins.length
    ? `${pageStart + 1}–${pageStart + visibleCoins.length} of ${coins.length}`
    : '--';

  return (
    <div className="surface overflow-hidden">
      <div className="px-4 py-2.5 border-b border-line flex items-center justify-between gap-4">
        <h2 className="text-md font-semibold text-fg">
          {marketType === 'nasdaq' ? 'Stock Assets' : 'Crypto Assets'}
        </h2>

        <div className="flex items-center gap-4 text-xs text-fg-subtle">
          {marketType === 'crypto' && (
            <div
              className={`flex items-center gap-1.5 ${isConnected ? 'ws-connected' : 'ws-disconnected'}`}
            >
              {isConnected ? (
                <>
                  <Wifi className="w-3 h-3" />
                  <span className="live-indicator">Live</span>
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3" />
                  <span>Connecting…</span>
                </>
              )}
            </div>
          )}
          <span className="tabnum">
            {rangeLabel} {marketType === 'nasdaq' ? 'stocks' : 'assets'}
          </span>
        </div>
      </div>

      {/* Column headers */}
      <div className={`${GRID} py-1.5 border-b border-line bg-surface-2`}>
        <div className="label text-center">#</div>
        <div className="label">Name</div>
        <div className="label text-right">Price</div>
        <div className="label text-right">24h %</div>
        <div className="label text-right">7d %</div>
        <div className="label text-right">Market Cap</div>
        <div className="label text-right">Volume 24h</div>
        <div className="label text-right">Last 7 Days</div>
      </div>

      <div className="divide-y divide-line">
        {isLoading
          ? [...Array(8)].map((_, i) => (
              <div key={i} className={`${GRID} py-3`}>
                <div className="flex justify-center">
                  <div className="w-4 h-4 rounded bg-surface-2 shimmer" />
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-full bg-surface-2 shimmer" />
                  <div className="space-y-1.5">
                    <div className="w-20 h-3 rounded bg-surface-2 shimmer" />
                    <div className="w-10 h-2.5 rounded bg-surface-2 shimmer" />
                  </div>
                </div>
                {[...Array(6)].map((_, j) => (
                  <div key={j} className="h-4 rounded bg-surface-2 shimmer ml-auto w-16" />
                ))}
              </div>
            ))
          : visibleCoins.map((coin, index) => {
              // Real series both ways — CoinGecko for coins, Yahoo's spark
              // endpoint for stocks. A row the source has no week of history
              // for shows `--` rather than a fabricated series.
              const sparklineData = coin.sparkline ?? [];
              const change7d = coin.change_7d;

              const rtPrice = getRealTimePrice(coin.symbol);
              const displayPrice = rtPrice?.price || coin.price;
              const flashClass = rtPrice?.flashClass || '';

              return (
                <div
                  key={coin.symbol}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedAsset(coin.symbol)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelectedAsset(coin.symbol);
                    }
                  }}
                  className={`${GRID} py-2.5 hover:bg-surface-2 transition-colors cursor-pointer`}
                >
                  <div className="flex items-center justify-center text-sm font-mono tabnum text-fg-subtle">
                    {pageStart + index + 1}
                  </div>

                  <div className="flex items-center gap-3 min-w-0">
                    <img
                      src={getAssetLogo(coin.symbol, coin.logo, marketType)}
                      alt=""
                      className="w-7 h-7 rounded-full object-cover bg-surface-2 shrink-0"
                      onError={(e) => {
                        e.currentTarget.src = `https://ui-avatars.com/api/?name=${coin.symbol}&background=232328&color=e8e8ea&size=64&bold=true`;
                      }}
                    />
                    <div className="min-w-0">
                      <p className="text-base text-fg truncate">
                        {getAssetName(coin.symbol, coin.name)}
                      </p>
                      <p className="text-xs text-fg-subtle">{coin.symbol}</p>
                    </div>
                  </div>

                  <div
                    className={`flex items-center justify-end font-mono text-base text-fg rounded px-1.5 price-cell ${flashClass}`}
                  >
                    {formatPrice(displayPrice)}
                  </div>

                  <div className="flex items-center justify-end">
                    <span
                      className={`flex items-center gap-0.5 text-base font-mono tabnum ${coin.change_24h >= 0 ? 'text-up' : 'text-down'}`}
                    >
                      {coin.change_24h >= 0 ? (
                        <ArrowUp className="w-3 h-3" />
                      ) : (
                        <ArrowDown className="w-3 h-3" />
                      )}
                      {Math.abs(coin.change_24h).toFixed(2)}%
                    </span>
                  </div>

                  <div className="flex items-center justify-end">
                    {change7d == null ? (
                      <span className="text-base font-mono tabnum text-fg-subtle">--</span>
                    ) : (
                      <span
                        className={`text-base font-mono tabnum ${change7d >= 0 ? 'text-up' : 'text-down'}`}
                      >
                        {change7d >= 0 ? '+' : ''}
                        {change7d.toFixed(2)}%
                      </span>
                    )}
                  </div>

                  <div className="flex items-center justify-end text-base font-mono tabnum text-fg-muted">
                    {formatVolume(coin.market_cap)}
                  </div>

                  <div className="flex items-center justify-end text-base font-mono tabnum text-fg-muted">
                    {formatVolume(coin.volume_24h)}
                  </div>

                  <div className="flex items-center justify-end">
                    {sparklineData.length > 1 && (
                      <SparklineChart
                        data={sparklineData}
                        // A 7-day series is coloured by its own direction. It
                        // used to follow change_24h, which was consistent only
                        // because the series was derived from that number —
                        // with real data an asset is routinely up on the day
                        // and down on the week.
                        positive={sparklineData[sparklineData.length - 1] >= sparklineData[0]}
                      />
                    )}
                  </div>
                </div>
              );
            })}
      </div>

      {!isLoading && totalPages > 1 && (
        <div className="px-4 py-2.5 border-t border-line flex items-center justify-between gap-4">
          <span className="text-xs text-fg-subtle tabnum">
            Page {currentPage} of {totalPages}
          </span>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage(currentPage - 1)}
              disabled={currentPage <= 1}
              aria-label="Previous page"
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-40 disabled:pointer-events-none transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Prev
            </button>
            <button
              type="button"
              onClick={() => setPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
              aria-label="Next page"
              className="flex items-center gap-1 px-2.5 py-1 rounded text-xs text-fg-muted hover:bg-surface-2 hover:text-fg disabled:opacity-40 disabled:pointer-events-none transition-colors"
            >
              Next
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {selectedAsset && (
        <AssetDetailModal
          symbol={selectedAsset}
          marketType={marketType}
          onClose={() => setSelectedAsset(undefined)}
        />
      )}
    </div>
  );
}
