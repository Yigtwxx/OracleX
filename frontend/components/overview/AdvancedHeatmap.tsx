'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Code,
  Gauge,
  RefreshCw,
  Repeat,
  Search,
  TrendingUp,
  Volume2,
  X,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { useHeatmap } from '@/hooks/queries';
import type { HeatmapCoin, HeatmapSector } from '@/lib/api';
import {
  bucketFor,
  PRICE_SCALE,
  SCORE_SCALE,
  TURNOVER_SCALE,
  UNKNOWN_BUCKET,
  VOLUME_SCALE,
  type HeatBucket,
} from '@/lib/heatmap-scale';
import { insetTile, squarify, type TreemapTile } from '@/lib/treemap';
import { formatLargeNumber, formatPrice, formatVolume } from './overview-utils';
import ToggleGroup from '@/components/ui/ToggleGroup';
import StatusMessage from '@/components/ui/StatusMessage';
import StaleStrip, { ENGLISH_LABELS } from '@/components/ui/StaleStrip';

// ─────────────────────────────────────────────────────────────────────────────
// Metrics
// ─────────────────────────────────────────────────────────────────────────────

export const METRICS = ['price', 'volume', 'turnover', 'developer'] as const;
export type MetricType = (typeof METRICS)[number];

type Timeframe = '24h' | '7d';
type ViewMode = 'treemap' | 'sector';

interface MetricConfig {
  label: string;
  icon: LucideIcon;
  /** Reads the value colour is derived from. An accessor, not a string key —
   *  the previous `coin[field as keyof CoinData]` cast was unchecked, so
   *  renaming a field compiled cleanly and rendered every tile as "—". */
  value: (coin: HeatmapCoin, timeframe: Timeframe) => number | undefined;
  /** What the tile prints. Always a real unit, never the 0-100 colour score:
   *  showing a normalised number as though it were a measurement is part of
   *  what made the old board feel invented. */
  display: (coin: HeatmapCoin, timeframe: Timeframe) => string;
  scale: readonly HeatBucket[];
  /** Shown when the whole board has no reading for this metric. */
  emptyHint: string;
}

function formatPercent(value: number | undefined, signed: boolean): string {
  if (value === undefined) return '—';
  const sign = signed && value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

export const METRIC_CONFIG: Record<MetricType, MetricConfig> = {
  price: {
    label: 'Price change',
    icon: TrendingUp,
    value: (coin, timeframe) =>
      timeframe === '24h' ? coin.price_change_24h : coin.price_change_7d,
    display: (coin, timeframe) =>
      formatPercent(timeframe === '24h' ? coin.price_change_24h : coin.price_change_7d, true),
    scale: PRICE_SCALE,
    emptyHint: 'No price changes reported for these assets.',
  },
  volume: {
    label: 'Volume',
    icon: Volume2,
    value: (coin) => coin.volume_score,
    display: (coin) => (coin.volume_24h === undefined ? '—' : formatVolume(coin.volume_24h)),
    scale: VOLUME_SCALE,
    emptyHint: 'No trading volume reported for these assets.',
  },
  turnover: {
    label: 'Turnover',
    icon: Repeat,
    value: (coin) => coin.turnover_pct,
    display: (coin) => formatPercent(coin.turnover_pct, false),
    scale: TURNOVER_SCALE,
    emptyHint: 'Turnover needs both volume and market cap, and neither is reported yet.',
  },
  developer: {
    label: 'Developer',
    icon: Code,
    value: (coin) => coin.developer_score,
    display: (coin) =>
      coin.developer_score === undefined ? '—' : String(Math.round(coin.developer_score)),
    scale: SCORE_SCALE,
    // The honest explanation: CoinGecko's anonymous tier refuses the per-coin
    // endpoint these scores come from, so without a key they never resolve.
    emptyHint:
      'Developer activity comes from one CoinGecko request per asset. The anonymous ' +
      'tier rate-limits that endpoint, so set COINGECKO_API_KEY to populate it.',
  },
};

const TIMEFRAMES: { value: Timeframe; label: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
];

const COIN_COUNTS = [25, 50, 100] as const;

/** Gutter between tiles, applied as an inset so it never distorts the areas. */
const TILE_GAP = 3;

const UNCLASSIFIED_SECTOR = 'Unclassified';

// ─────────────────────────────────────────────────────────────────────────────
// Presentation helpers
// ─────────────────────────────────────────────────────────────────────────────

function sectorLabel(coin: HeatmapCoin): string {
  return coin.sector ?? 'not classified yet';
}

/** What a screen reader hears instead of the tile's cramped visible text. */
function tileDescription(coin: HeatmapCoin, metric: MetricType, timeframe: Timeframe): string {
  const config = METRIC_CONFIG[metric];
  return [
    `${coin.name} (${coin.symbol}).`,
    `Market cap ${formatLargeNumber(coin.market_cap)}.`,
    `${config.label} ${timeframe === '7d' && metric === 'price' ? 'over 7 days' : ''} ${config.display(coin, timeframe)}.`.replace(
      /\s+/g,
      ' '
    ),
    `Sector ${sectorLabel(coin)}.`,
  ].join(' ');
}

// ─────────────────────────────────────────────────────────────────────────────
// Tile
// ─────────────────────────────────────────────────────────────────────────────

interface TileProps {
  coin: HeatmapCoin;
  tile: TreemapTile;
  metric: MetricType;
  timeframe: Timeframe;
  selected: boolean;
  onSelect: (coin: HeatmapCoin) => void;
}

function Tile({ coin, tile, metric, timeframe, selected, onSelect }: TileProps) {
  const config = METRIC_CONFIG[metric];
  const bucket = bucketFor(config.value(coin, timeframe), config.scale);
  const { x, y, w, h } = insetTile(tile, TILE_GAP);

  // Content is chosen by measured size, not by rank. Deciding by index is how
  // the previous board ended up printing a full name and price into a 60px box.
  // Below the symbol threshold nothing is drawn at all: a single clipped letter
  // is noise, and the aria-label and detail panel carry the whole row anyway.
  const showSymbol = w >= 30 && h >= 18;
  const showValue = w >= 56 && h >= 40;
  const showDetail = w >= 96 && h >= 68;

  return (
    <button
      type="button"
      aria-label={tileDescription(coin, metric, timeframe)}
      aria-pressed={selected}
      onClick={() => onSelect(coin)}
      onFocus={() => onSelect(coin)}
      // Deliberately not on hover. The panel is an `aria-live` region and
      // `aria-pressed` is real state: selecting on mouseover would make it
      // chatter on every pass of the cursor and would silently overwrite a
      // selection made with the keyboard.
      style={{ left: x, top: y, width: w, height: h }}
      // The ink comes from the bucket alongside its background — the brightest
      // ramp stop needs dark text, every other stop needs light. Nothing here
      // sets a text colour of its own, and nothing uses a muted or translucent
      // one: on a saturated tile those land near 2:1, and the biggest movers
      // are exactly the tiles worth reading.
      className={`absolute overflow-hidden p-1.5 transition-shadow hover:shadow-lg
        focus-visible:z-20 ${
          // A 12px tile with a 6px radius reads as a dot, not a tile.
          showSymbol ? 'rounded-md' : 'rounded-sm'
        } ${bucket.className} ${selected ? 'z-10 ring-1 ring-fg/50' : ''}`}
    >
      <div
        className={`flex h-full flex-col overflow-hidden ${
          // Small tiles anchor top-left so the symbol survives the crop; large
          // ones centre, otherwise a 700px BTC tile strands its label at the
          // very top and its figure at the very bottom.
          showValue ? 'items-center justify-center gap-0.5' : 'items-start justify-start'
        }`}
      >
        {showSymbol && (
          <span className="block max-w-full truncate text-xs font-semibold leading-tight">
            {coin.symbol}
          </span>
        )}
        {showValue && (
          <span className="block max-w-full truncate text-base font-bold leading-tight">
            {config.display(coin, timeframe)}
          </span>
        )}
        {showDetail && (
          <span className="block max-w-full truncate text-[11px] leading-tight opacity-90">
            {coin.price === undefined ? '—' : formatPrice(coin.price)}
          </span>
        )}
      </div>
    </button>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Treemap surface
// ─────────────────────────────────────────────────────────────────────────────

interface BoardProps {
  coins: HeatmapCoin[];
  metric: MetricType;
  timeframe: Timeframe;
  selectedId: string | undefined;
  onSelect: (coin: HeatmapCoin) => void;
}

function TreemapBoard({ coins, metric, timeframe, selectedId, onSelect }: BoardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Area is market cap, always — the one thing on the board that means
  // "how much this asset matters". Colour carries the selected metric.
  const tiles = useMemo(
    () =>
      squarify(
        coins.map((coin) => ({ id: coin.id, value: coin.market_cap })),
        size.width,
        size.height
      ),
    [coins, size.width, size.height]
  );

  const byId = useMemo(() => new Map(coins.map((coin) => [coin.id, coin])), [coins]);

  return (
    <div ref={containerRef} className="relative h-full w-full">
      {tiles.map((tile) => {
        const coin = byId.get(tile.id);
        if (!coin) return undefined;
        return (
          <Tile
            key={tile.id}
            coin={coin}
            tile={tile}
            metric={metric}
            timeframe={timeframe}
            selected={selectedId === coin.id}
            onSelect={onSelect}
          />
        );
      })}
    </div>
  );
}

/** Sectors laid out by their own market cap, each holding its members' tiles. */
function SectorBoard({
  sectors,
  metric,
  timeframe,
  selectedId,
  onSelect,
}: Omit<BoardProps, 'coins'> & { sectors: HeatmapSector[] }) {
  return (
    <div className="flex flex-col gap-3 overflow-y-auto pb-2">
      {sectors.map((sector) => {
        const change = sector.weighted_change_24h;
        return (
          <section
            key={sector.sector}
            className="rounded-lg border border-line bg-surface p-3"
            aria-label={`${sector.sector} sector`}
          >
            <header className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 className="text-sm font-semibold text-fg">{sector.sector}</h3>
              <span className="text-xs text-fg-muted">
                {sector.coin_count} {sector.coin_count === 1 ? 'asset' : 'assets'} ·{' '}
                {formatLargeNumber(sector.market_cap)}
              </span>
              <span
                className={`text-xs font-medium ${
                  change === undefined ? 'text-fg-muted' : change >= 0 ? 'text-up' : 'text-down'
                }`}
              >
                {/* Weighted, and labelled as such: a plain mean of members lets
                    a $300M token move a sector as much as a $2T one. */}
                {change === undefined ? 'no reading' : `${formatPercent(change, true)} weighted`}
              </span>
              {sector.coverage < 1 && (
                <span className="text-xs text-warn">
                  {Math.round(sector.coverage * 100)}% measured
                </span>
              )}
            </header>
            <div className="relative h-32">
              <TreemapBoard
                coins={sector.coins}
                metric={metric}
                timeframe={timeframe}
                selectedId={selectedId}
                onSelect={onSelect}
              />
            </div>
          </section>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Detail panel
// ─────────────────────────────────────────────────────────────────────────────

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="text-xs font-medium text-fg">{value}</dd>
    </div>
  );
}

/**
 * Replaces the hover tooltip entirely.
 *
 * The tooltip was absolutely positioned inside an `overflow-auto` ancestor, so
 * the whole first row — the largest, most-looked-at tiles — had it clipped. It
 * was also mouse-only, which put market cap, sector, turnover and developer
 * activity permanently out of reach of a keyboard or a screen reader. A panel
 * fed by both click and focus fixes both, and cannot be clipped.
 */
function DetailPanel({ coin, timeframe }: { coin: HeatmapCoin | undefined; timeframe: Timeframe }) {
  // The live region is mounted whether or not anything is selected: a region
  // that appears at the same moment as its content is not reliably announced,
  // so an empty one has to be sitting there first.
  if (!coin) {
    return (
      <aside
        className="shrink-0 border-t border-line bg-surface px-4 py-2"
        aria-live="polite"
        aria-label="Selected asset"
      >
        <p className="text-xs text-fg-muted">
          Select an asset — click, or Tab to it — to see its full figures.
        </p>
      </aside>
    );
  }

  const change = timeframe === '24h' ? coin.price_change_24h : coin.price_change_7d;

  return (
    <aside
      className="shrink-0 border-t border-line bg-surface px-4 py-2"
      aria-live="polite"
      aria-label="Selected asset"
    >
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-fg">
          {coin.name} <span className="text-xs font-normal text-fg-muted">{coin.symbol}</span>
        </h3>
        {coin.peg_type && (
          <span className="rounded border border-line px-1.5 text-[11px] text-fg-muted">
            {coin.peg_type}
          </span>
        )}
        <span
          className={`text-sm font-medium ${
            change === undefined ? 'text-fg-muted' : change >= 0 ? 'text-up' : 'text-down'
          }`}
        >
          {formatPercent(change, true)} <span className="text-xs">{timeframe}</span>
        </span>
      </div>
      <dl className="mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 sm:grid-cols-3 lg:grid-cols-5">
        <DetailRow label="Price" value={coin.price === undefined ? '—' : formatPrice(coin.price)} />
        <DetailRow label="Market cap" value={formatLargeNumber(coin.market_cap)} />
        <DetailRow
          label="Volume 24h"
          value={coin.volume_24h === undefined ? '—' : formatVolume(coin.volume_24h)}
        />
        <DetailRow label="Turnover" value={formatPercent(coin.turnover_pct, false)} />
        <DetailRow
          label="Developer"
          value={
            coin.developer_score === undefined ? '—' : String(Math.round(coin.developer_score))
          }
        />
      </dl>
      <p className="mt-1 text-xs text-fg-muted">Sector: {sectorLabel(coin)}</p>
    </aside>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Chrome
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Rendered from the same array `bucketFor` walks.
 *
 * The hand-written legend this replaces disagreed with the colour function: it
 * showed a swatch the price scale never produces and omitted two buckets it
 * does. A test asserts every entry here maps back to its own bucket.
 */
function Legend({ metric }: { metric: MetricType }) {
  const scale = METRIC_CONFIG[metric].scale;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs">
      {scale.map((bucket) => (
        <span key={bucket.className + bucket.label} className="flex items-center gap-1">
          <span className={`h-3 w-3 rounded ${bucket.className}`} aria-hidden="true" />
          <span className="text-fg-muted">{bucket.label}</span>
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span className={`h-3 w-3 rounded ${UNKNOWN_BUCKET.className}`} aria-hidden="true" />
        <span className="text-fg-muted">{UNKNOWN_BUCKET.label}</span>
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Board
// ─────────────────────────────────────────────────────────────────────────────

export default function AdvancedHeatmap() {
  const [metric, setMetric] = useState<MetricType>('price');
  const [timeframe, setTimeframe] = useState<Timeframe>('24h');
  const [view, setView] = useState<ViewMode>('treemap');
  const [limit, setLimit] = useState<number>(50);
  const [includePegged, setIncludePegged] = useState(false);
  const [sectorFilter, setSectorFilter] = useState<string>('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | undefined>(undefined);

  const { data, isLoading, isFetching, isError, error, refetch } = useHeatmap(limit, includePegged);

  // Debounced so typing does not re-run the layout on every keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim().toLowerCase()), 150);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const coins = useMemo(() => {
    if (!data) return [];
    return data.coins.filter((coin) => {
      if (sectorFilter === UNCLASSIFIED_SECTOR && coin.sector !== undefined) return false;
      if (
        sectorFilter !== 'all' &&
        sectorFilter !== UNCLASSIFIED_SECTOR &&
        coin.sector !== sectorFilter
      ) {
        return false;
      }
      if (!search) return true;
      return coin.symbol.toLowerCase().includes(search) || coin.name.toLowerCase().includes(search);
    });
  }, [data, sectorFilter, search]);

  const sectors = useMemo(() => {
    if (!data) return [];
    const visible = new Set(coins.map((coin) => coin.id));
    return data.sectors
      .map((sector) => ({
        ...sector,
        coins: sector.coins.filter((coin) => visible.has(coin.id)),
      }))
      .filter((sector) => sector.coins.length > 0);
  }, [data, coins]);

  const selected = useMemo(() => coins.find((coin) => coin.id === selectedId), [coins, selectedId]);

  const handleSelect = useCallback((coin: HeatmapCoin) => setSelectedId(coin.id), []);

  const clearFilters = useCallback(() => {
    setSearchInput('');
    setSectorFilter('all');
  }, []);

  const hasFilters = search !== '' || sectorFilter !== 'all';
  const metricIsEmpty =
    coins.length > 0 &&
    coins.every((coin) => METRIC_CONFIG[metric].value(coin, timeframe) === undefined);

  // A failed refresh must never blank a populated board — react-query retains
  // the previous `data`, so the error becomes a badge rather than a full-screen
  // takeover. Only a cold failure gets the error state.
  const showColdError = isError && !data;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-1.5">
        <ToggleGroup
          label="Metric"
          value={metric}
          onChange={setMetric}
          options={METRICS.map((value) => ({
            value,
            label: METRIC_CONFIG[value].label,
            icon: METRIC_CONFIG[value].icon,
          }))}
        />
        <div className="flex items-center gap-3">
          {metric === 'price' && (
            <ToggleGroup
              label="Timeframe"
              value={timeframe}
              onChange={setTimeframe}
              options={TIMEFRAMES}
            />
          )}
          <ToggleGroup
            label="View"
            value={view}
            onChange={setView}
            options={[
              { value: 'treemap', label: 'Treemap' },
              { value: 'sector', label: 'Sector' },
            ]}
          />
          <button
            type="button"
            aria-label="Refresh heatmap"
            title="Refresh heatmap"
            onClick={() => refetch()}
            disabled={isFetching}
            className="rounded-md border border-line p-1.5 text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3 w-3 ${isFetching ? 'animate-spin' : ''}`}
              aria-hidden="true"
            />
          </button>
        </div>
      </div>

      {/* Filters + provenance */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-1.5 text-xs">
        <label className="flex items-center gap-1.5">
          <Search className="h-3 w-3 text-fg-muted" aria-hidden="true" />
          <span className="sr-only">Search assets</span>
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search"
            className="w-24 rounded-md border border-line bg-bg px-2 py-0.5 text-fg placeholder:text-fg-subtle focus:border-line-strong focus:outline-none"
          />
        </label>

        <label className="flex items-center gap-1.5 text-fg-muted">
          Sector
          <select
            value={sectorFilter}
            onChange={(event) => setSectorFilter(event.target.value)}
            className="rounded-md border border-line bg-bg px-1.5 py-0.5 text-fg focus:border-line-strong focus:outline-none"
          >
            <option value="all">All</option>
            {(data?.sectors ?? []).map((sector) => (
              <option key={sector.sector} value={sector.sector}>
                {sector.sector}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-fg-muted">
          Assets
          <select
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
            className="rounded-md border border-line bg-bg px-1.5 py-0.5 text-fg focus:border-line-strong focus:outline-none"
          >
            {COIN_COUNTS.map((count) => (
              <option key={count} value={count}>
                {count}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5 text-fg-muted">
          <input
            type="checkbox"
            checked={includePegged}
            onChange={(event) => setIncludePegged(event.target.checked)}
            className="accent-accent"
          />
          Include stablecoins &amp; wrapped
          {data && data.excluded_pegged > 0 && !includePegged && (
            <span className="text-fg-subtle">({data.excluded_pegged} hidden)</span>
          )}
        </label>

        {hasFilters && (
          <button
            type="button"
            onClick={clearFilters}
            className="flex items-center gap-1 text-fg-muted hover:text-fg"
          >
            <X className="h-3 w-3" aria-hidden="true" />
            Clear filters
          </button>
        )}

        {/* States the encoding out loud. Without it, area is an unexplained
            visual channel — which is exactly how the old index-based sizing
            went unnoticed. */}
        <span className="ml-auto text-fg-subtle">
          Area: market cap · Colour: {METRIC_CONFIG[metric].label.toLowerCase()}
        </span>
      </div>

      {/* Staleness / refresh failure — a badge, never a takeover */}
      {data && (data.stale || isError) && (
        <div className="shrink-0 border-b border-line px-4 py-1">
          <StaleStrip
            stale={data.stale}
            refreshFailed={isError}
            ageSeconds={data.age_seconds}
            onRetry={() => refetch()}
            labels={ENGLISH_LABELS}
          />
        </div>
      )}

      {/* Board */}
      <div className="min-h-0 flex-1 p-3">
        {isLoading && !data ? (
          <StatusMessage icon={RefreshCw}>Loading the board…</StatusMessage>
        ) : showColdError ? (
          <StatusMessage
            icon={AlertTriangle}
            action={
              <button
                type="button"
                onClick={() => refetch()}
                className="mt-1 rounded-md border border-line px-2.5 py-1 text-sm text-fg-muted hover:text-fg"
              >
                Retry
              </button>
            }
          >
            {error instanceof Error
              ? `Market data is unavailable right now. (${error.message})`
              : 'Market data is unavailable right now.'}
          </StatusMessage>
        ) : coins.length === 0 ? (
          <StatusMessage
            icon={Search}
            action={
              hasFilters ? (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="mt-1 rounded-md border border-line px-2.5 py-1 text-sm text-fg-muted hover:text-fg"
                >
                  Clear filters
                </button>
              ) : undefined
            }
          >
            {hasFilters
              ? `No assets match ${search ? `"${searchInput}"` : 'this sector'}.`
              : 'No assets on the board.'}
          </StatusMessage>
        ) : metricIsEmpty ? (
          <StatusMessage icon={Gauge}>{METRIC_CONFIG[metric].emptyHint}</StatusMessage>
        ) : view === 'treemap' ? (
          <TreemapBoard
            coins={coins}
            metric={metric}
            timeframe={timeframe}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        ) : (
          <SectorBoard
            sectors={sectors}
            metric={metric}
            timeframe={timeframe}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        )}
      </div>

      <DetailPanel coin={selected} timeframe={timeframe} />

      <div className="shrink-0 border-t border-line bg-surface p-2">
        <Legend metric={metric} />
      </div>
    </div>
  );
}
