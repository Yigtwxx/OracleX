'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowUp,
  ArrowDown,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Search,
  WifiOff,
  X,
} from 'lucide-react';
import { MarketOverview } from '@/lib/api';
import SparklineChart from './SparklineChart';
import { useWebSocketPrices } from '@/hooks/useWebSocketPrices';
import AssetDetailModal from './AssetDetailModal';
import { getAssetLogo, getAssetName, formatPrice, formatVolume } from './overview-utils';
import {
  ColumnKey,
  columnsForMarket,
  loadColumns,
  rangePosition,
  saveColumns,
  turnoverPct,
} from './table-columns';

interface AssetTableProps {
  marketData: MarketOverview | null;
  marketType: 'crypto' | 'nasdaq';
  isLoading: boolean;
}

// Widths of the columns that are always present, in render order:
// #, Name, Price, 24h %, 7d %, Market Cap, Volume 24h — with the sparkline
// appended after whatever optional columns are switched on.
const BASE_WIDTHS = ['40px', 'minmax(0,1fr)', '120px', '100px', '100px', '130px', '130px'];
const SPARKLINE_WIDTH = '110px';

// The API returns 250 rows. Rendering them all at once means 250 inline SVG
// sparklines on first paint, so the table pages instead.
const PAGE_SIZE = 50;

/**
 * Position of the current price inside a low–high band. Renders `--` when the
 * band is unreported rather than drawing a marker at an arbitrary spot.
 */
function RangeCell({
  low,
  high,
  price,
  title,
}: {
  low?: number;
  high?: number;
  price: number;
  title: string;
}) {
  const position = rangePosition(low, high, price);

  if (position === undefined) {
    return <span className="text-base font-mono tabnum text-fg-subtle">--</span>;
  }

  return (
    <div className="w-full flex items-center" title={title}>
      <div className="relative w-full h-1 rounded-full bg-surface-2">
        <span
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-1.5 h-2.5 rounded-sm"
          style={{
            left: `${position * 100}%`,
            background: position >= 0.5 ? 'var(--up)' : 'var(--down)',
          }}
        />
      </div>
    </div>
  );
}

export default function AssetTable({ marketData, marketType, isLoading }: AssetTableProps) {
  const [selectedAsset, setSelectedAsset] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [activeColumns, setActiveColumns] = useState<ColumnKey[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Which column the pointer is over, so its header can say so. The table is a
  // CSS grid of independent row divs, not a <table>, so there is no column
  // element to hang `:hover` on — the pointer's x is mapped onto the header
  // cells, which are what define the grid in the first place.
  const headerRowRef = useRef<HTMLDivElement>(null);
  const [hoverCol, setHoverCol] = useState<number | null>(null);
  // Viewport-space bounds of the column currently marked, so an ordinary mouse
  // move inside it costs one comparison instead of a full round of
  // getBoundingClientRect() calls.
  const hoverBoundsRef = useRef<{ left: number; right: number } | null>(null);

  // WebSocket for real-time crypto prices
  const { prices: wsPrices, isConnected } = useWebSocketPrices({
    enabled: marketType === 'crypto',
  });

  const getRealTimePrice = (symbol: string) => {
    if (marketType !== 'crypto') return undefined;
    const normalizedSymbol = symbol.replace('USDT', '').replace('/', '').toUpperCase();
    return wsPrices[normalizedSymbol];
  };

  // The column choice is a stored preference, so it is read on the client only
  // — rendering the default on the server keeps hydration stable.
  useEffect(() => {
    setActiveColumns(loadColumns());
  }, []);

  useEffect(() => {
    if (!pickerOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) {
        setPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [pickerOpen]);

  const available = useMemo(() => columnsForMarket(marketType), [marketType]);

  // A column switched on for stocks (52W range) must not survive a jump to the
  // crypto list, where nothing reports it.
  const visibleColumns = useMemo(
    () => available.filter((c) => activeColumns.includes(c.key)),
    [available, activeColumns]
  );

  const gridStyle = useMemo(
    () => ({
      gridTemplateColumns: [
        ...BASE_WIDTHS,
        ...visibleColumns.map((c) => c.width),
        SPARKLINE_WIDTH,
      ].join(' '),
    }),
    [visibleColumns]
  );

  const clearHover = () => {
    hoverBoundsRef.current = null;
    setHoverCol(null);
  };

  // A resize or a column toggle moves every cell, which would leave the wrong
  // header marked until the pointer next crossed a boundary.
  useEffect(() => {
    clearHover();
  }, [visibleColumns]);

  useEffect(() => {
    window.addEventListener('resize', clearHover);
    return () => window.removeEventListener('resize', clearHover);
  }, []);

  const handleHoverMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const bounds = hoverBoundsRef.current;
    const x = event.clientX;
    if (bounds && x >= bounds.left && x < bounds.right) return;

    const header = headerRowRef.current;
    if (!header) return;

    const cells = Array.from(header.children) as HTMLElement[];

    for (let i = 0; i < cells.length; i += 1) {
      const rect = cells[i].getBoundingClientRect();
      if (x >= rect.left && x < rect.right) {
        hoverBoundsRef.current = { left: rect.left, right: rect.right };
        setHoverCol(i);
        return;
      }
    }

    // The pointer is in one of the grid's gutters — keep the last column
    // rather than flickering the mark off and on across an 8px gap.
  };

  const headerClass = (index: number, align = 'text-right') =>
    `label ${align} transition-colors ${hoverCol === index ? 'text-fg' : ''}`;

  const toggleColumn = (key: ColumnKey) => {
    setActiveColumns((current) => {
      const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
      saveColumns(next);
      return next;
    });
  };

  const allCoins = useMemo(() => marketData?.coins ?? [], [marketData]);

  // Search covers the whole payload, not the visible page — typing "sol" on
  // page 1 should find Solana wherever it ranks, otherwise the box would only
  // ever confirm what is already on screen.
  const coins = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return allCoins;
    return allCoins.filter((coin) =>
      `${coin.symbol} ${coin.name ?? ''}`.toLowerCase().includes(needle)
    );
  }, [allCoins, query]);

  const totalPages = Math.max(1, Math.ceil(coins.length / PAGE_SIZE));

  // Switching between crypto and stocks swaps the whole list out from under
  // whatever page the user was on, and carries over a query that means nothing
  // in the other market.
  useEffect(() => {
    setPage(1);
    setQuery('');
    setSearchOpen(false);
  }, [marketType]);

  // Narrowing the list has the same effect as switching markets.
  useEffect(() => {
    setPage(1);
  }, [query]);

  // A refresh can shrink the list; never strand the user past the last page.
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const visibleCoins = coins.slice(pageStart, pageStart + PAGE_SIZE);

  const noun = marketType === 'nasdaq' ? 'stocks' : 'assets';
  const searching = query.trim().length > 0;
  const rangeLabel = coins.length
    ? // While searching, the payload total stays in view so the count reads as
      // "found this many out of that many" rather than as a shrunken market.
      `${pageStart + 1}–${pageStart + visibleCoins.length} of ${coins.length}${
        searching ? ` (${allCoins.length})` : ''
      }`
    : '--';

  const closeSearch = () => {
    setQuery('');
    setSearchOpen(false);
  };

  return (
    <div className="surface overflow-hidden">
      <div className="px-4 py-2.5 border-b border-line flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5 min-w-0">
          <h2 className="text-md font-semibold text-fg whitespace-nowrap">
            {marketType === 'nasdaq' ? 'Stock Assets' : 'Crypto Assets'}
          </h2>

          {/* Collapsed it is just the icon; clicking it grows the capsule and
              focuses the field. It stays open while there is a query so the
              filtered count keeps its explanation on screen. */}
          <div
            className="glass-search"
            role="search"
            data-open={searchOpen || searching}
            onClick={() => {
              setSearchOpen(true);
              searchInputRef.current?.focus();
            }}
          >
            <Search className="w-3.5 h-3.5 shrink-0 text-fg-muted" aria-hidden />
            <input
              ref={searchInputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={() => setSearchOpen(true)}
              onBlur={() => {
                if (!searching) setSearchOpen(false);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  closeSearch();
                  e.currentTarget.blur();
                }
              }}
              placeholder={marketType === 'nasdaq' ? 'Ticker or company' : 'Symbol or name'}
              aria-label={`Search ${noun}`}
            />
            {searching && (
              <button
                type="button"
                onClick={closeSearch}
                aria-label="Clear search"
                className="shrink-0 text-fg-subtle hover:text-fg transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs text-fg-subtle">
          {/* The global Live badge in the header covers the healthy case, so
              only the degraded socket state is worth surfacing here. */}
          {marketType === 'crypto' && !isConnected && (
            <div className="flex items-center gap-1.5 ws-disconnected">
              <WifiOff className="w-3 h-3" />
              <span>Connecting…</span>
            </div>
          )}
          <span className="tabnum">
            {rangeLabel} {marketType === 'nasdaq' ? 'stocks' : 'assets'}
          </span>

          <div className="relative" ref={pickerRef}>
            <button
              type="button"
              onClick={() => setPickerOpen((v) => !v)}
              aria-expanded={pickerOpen}
              aria-haspopup="true"
              className="flex items-center gap-1 px-2 py-1 rounded text-xs text-fg-muted hover:bg-surface-2 hover:text-fg transition-colors"
            >
              <Columns3 className="w-3.5 h-3.5" />
              Columns
              <ChevronDown className="w-3 h-3" />
            </button>

            {pickerOpen && (
              <div className="absolute right-0 top-full mt-1 z-20 w-48 surface p-1 shadow-lg">
                {available.map((column) => (
                  <label
                    key={column.key}
                    className="flex items-center gap-2 px-2 py-1.5 rounded text-xs text-fg-muted hover:bg-surface-2 hover:text-fg cursor-pointer select-none transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={activeColumns.includes(column.key)}
                      onChange={() => toggleColumn(column.key)}
                      className="accent-[var(--accent)]"
                    />
                    {column.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div onMouseMove={handleHoverMove} onMouseLeave={clearHover}>
        {/* Column headers. The one the pointer is under lights up, so a value
            read halfway down a 50-row page still has a legible label. */}
        <div
          ref={headerRowRef}
          className="grid gap-2 px-4 py-1.5 border-b border-line bg-surface-2"
          style={gridStyle}
        >
          <div className={headerClass(0, 'text-center')}>#</div>
          <div className={headerClass(1, 'text-left')}>Name</div>
          <div className={headerClass(2)}>Price</div>
          <div className={headerClass(3)}>24h %</div>
          <div className={headerClass(4)}>7d %</div>
          <div className={headerClass(5)}>Market Cap</div>
          <div className={headerClass(6)}>Volume 24h</div>
          {visibleColumns.map((column, i) => (
            <div key={column.key} className={headerClass(BASE_WIDTHS.length + i)}>
              {column.label}
            </div>
          ))}
          <div className={headerClass(BASE_WIDTHS.length + visibleColumns.length)}>Last 7 Days</div>
        </div>

        <div className="divide-y divide-line">
          {isLoading
            ? [...Array(8)].map((_, i) => (
                <div key={i} className="grid gap-2 px-4 py-3" style={gridStyle}>
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
                  {[...Array(6 + visibleColumns.length)].map((_, j) => (
                    <div key={j} className="h-4 rounded bg-surface-2 shimmer ml-auto w-16" />
                  ))}
                </div>
              ))
            : visibleCoins.length === 0
              ? searching && (
                  <div className="px-4 py-10 text-center">
                    <p className="text-base text-fg-muted">
                      No {noun} match “{query.trim()}”.
                    </p>
                  </div>
                )
              : visibleCoins.map((coin, index) => {
                  // Real series both ways — CoinGecko for coins, Yahoo's spark
                  // endpoint for stocks. A row the source has no week of history
                  // for shows `--` rather than a fabricated series.
                  const sparklineData = coin.sparkline ?? [];
                  const change7d = coin.change_7d;

                  const rtPrice = getRealTimePrice(coin.symbol);
                  const displayPrice = rtPrice?.price || coin.price;
                  const flashClass = rtPrice?.flashClass || '';
                  const turnover = turnoverPct(coin);

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
                      className="grid gap-2 px-4 py-2.5 hover:bg-surface-2 transition-colors cursor-pointer"
                      style={gridStyle}
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

                      {visibleColumns.map((column) => {
                        switch (column.key) {
                          case 'range24h':
                            return (
                              <div key={column.key} className="flex items-center justify-end">
                                <RangeCell
                                  low={coin.low_24h}
                                  high={coin.high_24h}
                                  price={displayPrice}
                                  title={`24h ${formatPrice(coin.low_24h)} – ${formatPrice(coin.high_24h)}`}
                                />
                              </div>
                            );
                          case 'turnover':
                            return (
                              <div
                                key={column.key}
                                className="flex items-center justify-end text-base font-mono tabnum text-fg-muted"
                              >
                                {turnover === undefined ? '--' : `${turnover.toFixed(1)}%`}
                              </div>
                            );
                          case 'high24h':
                            return (
                              <div
                                key={column.key}
                                className="flex items-center justify-end text-base font-mono tabnum text-fg-muted"
                              >
                                {coin.high_24h == null ? '--' : formatPrice(coin.high_24h)}
                              </div>
                            );
                          case 'low24h':
                            return (
                              <div
                                key={column.key}
                                className="flex items-center justify-end text-base font-mono tabnum text-fg-muted"
                              >
                                {coin.low_24h == null ? '--' : formatPrice(coin.low_24h)}
                              </div>
                            );
                          case 'range52w':
                            return (
                              <div key={column.key} className="flex items-center justify-end">
                                <RangeCell
                                  low={coin.fifty_two_week_low}
                                  high={coin.fifty_two_week_high}
                                  price={displayPrice}
                                  title={
                                    coin.fifty_two_week_low != null &&
                                    coin.fifty_two_week_high != null
                                      ? `52W ${formatPrice(coin.fifty_two_week_low)} – ${formatPrice(coin.fifty_two_week_high)}`
                                      : '52W range unavailable'
                                  }
                                />
                              </div>
                            );
                        }
                      })}

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
