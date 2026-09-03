'use client';

import { AlertTriangle, ChevronRight, RefreshCw } from 'lucide-react';
import dynamic from 'next/dynamic';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useMemo } from 'react';

import DataTable, { type ColumnDef } from '@/components/ui/DataTable';
import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import { useBistPositioning, useBistPositioningNote } from '@/hooks/useBist';
import type { BistPositioningRow } from '@/lib/bist-api';
import {
  CAPITAL_ACTION_NOTE,
  formatCompact,
  formatCompactTry,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  formatTry,
  isLikelyCapitalAction,
  toneClass,
} from '@/lib/bist-format';
import {
  NEAR_EXTREME,
  QUADRANTS,
  QUADRANT_LABEL,
  RANGE_BUCKETS,
  applyFilter,
  crowdingPoints,
  futuresPoints,
  rangeHistogram,
  sectorAggregates,
  summarise,
  type PositioningFilter,
  type Quadrant,
} from '@/lib/bist-positioning';
import BistPageShell from './BistPageShell';
import BistPositioningNote from './BistPositioningNote';
import MetricTile from './MetricTile';
import FilterChips from './positioning/FilterChips';
import BistChartPanel from './BistChartPanel';
import RangeDistribution from './positioning/RangeDistribution';
import SectorCrowdingMap from './positioning/SectorCrowdingMap';

/**
 * The two ECharts panels load after mount; the two DOM panels do not.
 *
 * ECharts is about 350 kB, and statically importing it put this route's first
 * load at 534 kB against 103–182 kB for every page that does not chart. This
 * page used to be a table and cost nothing, so the whole difference is the
 * redesign's — worth paying for the panels, not worth paying before the board
 * has even arrived. Deferred, the payload lands near the rest of the terminal
 * and the charts fill in a beat later behind the same shimmer the data does.
 *
 * `ssr: false` because both resolve their palette from the live document:
 * ECharts paints to canvas and the 2D context ignores `var(--token)`, so a
 * server render would emit a chart in fallback colours and then repaint.
 */
const CrowdingScatter = dynamic(() => import('./positioning/CrowdingScatter'), {
  ssr: false,
  loading: () => <div className="shimmer h-[300px]" />,
});
const FuturesQuadrant = dynamic(() => import('./positioning/FuturesQuadrant'), {
  ssr: false,
  loading: () => <div className="shimmer h-[300px]" />,
});

/**
 * The whole board, not the crowded head of it.
 *
 * The endpoint returns rows ranked by crowding, so a smaller limit is a
 * *biased* sample by construction — and two of the four panels ask questions
 * about the market rather than about its busiest names. "Is the board stretched
 * against its own year" answered over the hundred most crowded stocks is not a
 * narrower answer, it is a wrong one. The route caps at 500.
 */
const BOARD_LIMIT = 500;

/** Where the price sits between its own 52-week extremes. */
function RangeBar({ position }: { position: number | null }) {
  if (position === null) return <span className="text-fg-subtle">—</span>;
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="relative h-1 w-14 overflow-hidden rounded-full bg-surface-2">
        <span
          className="absolute top-0 h-full w-0.5 bg-fg"
          style={{ left: `${Math.min(100, Math.max(0, position * 100))}%` }}
        />
      </span>
      <span className="tabnum text-2xs">{formatPercent(position, 0)}</span>
    </span>
  );
}

function readFilter(params: URLSearchParams): PositioningFilter {
  const quadrant = params.get('quadrant');
  const range = Number.parseInt(params.get('range') ?? '', 10);
  return {
    sector: params.get('sector') || undefined,
    quadrant: QUADRANTS.includes(quadrant as Quadrant) ? (quadrant as Quadrant) : undefined,
    rangeBucket: Number.isInteger(range) && range >= 0 && range < RANGE_BUCKETS ? range : undefined,
  };
}

/**
 * Positioning — who is leaning which way, from what the market publishes.
 *
 * The page carries its own caveat because it has to. It was specified as a
 * fund-to-stock cross index: invert every TEFAS portfolio and answer "which
 * funds moved into this name last month". That is not buildable — TEFAS
 * withdrew portfolio breakdowns from its public API in the 2026 rewrite and KAP
 * publishes fund holdings only as prose attachments. Quietly shipping a
 * different board under the same promise would be the dishonest option, so the
 * page says what it is and what it is not.
 *
 * Four panels rather than one table, because the four quantities have four
 * different shapes and a column of digits has none. Crowding is a ratio, so it
 * is drawn as the two axes it divides; futures positioning is a pair of signs,
 * so it is drawn as four quadrants; range position is a distribution; sector
 * heat is a part-of-whole. Each panel contributes a clause to one shared
 * filter, and the table underneath is what the filter resolves to — the detail
 * you arrive at, rather than the interface you start from.
 */
export default function BistSmartMoneyPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { data, isLoading, isError, isFetching, refetch } = useBistPositioning(BOARD_LIMIT);
  const note = useBistPositioningNote();

  const filter = useMemo(() => readFilter(new URLSearchParams(searchParams)), [searchParams]);

  // `replace`, not `push`: the filter is a view state rather than a step in a
  // journey, and pushing would make the back button walk out through every tile
  // the reader tried before the one they meant.
  const setFilter = useCallback(
    (next: PositioningFilter) => {
      const params = new URLSearchParams();
      if (next.sector) params.set('sector', next.sector);
      if (next.quadrant) params.set('quadrant', next.quadrant);
      if (next.rangeBucket !== undefined) params.set('range', String(next.rangeBucket));
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  const openStock = useCallback(
    (ticker: string) => router.push(`/bist/hisseler/${ticker}`),
    [router]
  );

  const rows = useMemo(() => data?.crowded ?? [], [data]);
  const futures = useMemo(() => data?.futures ?? [], [data]);
  const summary = useMemo(() => summarise(rows, futures), [rows, futures]);

  // A panel never filters itself. The clause it contributed comes back to it as
  // a *selection* instead, so its own choice stays visible among the options it
  // was chosen from — a sector map showing one tile would be a map of nothing.
  const filtered = useMemo(() => applyFilter(rows, filter), [rows, filter]);
  const forSectors = useMemo(
    () => sectorAggregates(applyFilter(rows, { ...filter, sector: undefined })),
    [rows, filter]
  );
  const forRange = useMemo(
    () => rangeHistogram(applyFilter(rows, { ...filter, rangeBucket: undefined })),
    [rows, filter]
  );
  const forQuadrant = useMemo(
    () => futuresPoints(applyFilter(futures, { ...filter, quadrant: undefined })),
    [futures, filter]
  );
  const points = useMemo(() => crowdingPoints(filtered), [filtered]);

  const columns = useMemo<ColumnDef<BistPositioningRow>[]>(
    () => [
      {
        key: 'ticker',
        label: 'Hisse',
        width: 'minmax(150px, 1.4fr)',
        sortValue: (row) => row.ticker,
        render: (row) => (
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate font-medium text-fg">{row.ticker}</span>
            <span className="truncate text-2xs text-fg-subtle">{row.sector}</span>
          </span>
        ),
      },
      {
        key: 'price',
        label: 'Fiyat',
        width: '104px',
        align: 'right',
        sortValue: (row) => row.price,
        render: (row) => <span className="tabnum">{formatTry(row.price)}</span>,
      },
      {
        key: 'change',
        label: 'Değişim',
        width: '96px',
        align: 'right',
        sortValue: (row) => row.change_pct,
        render: (row) => (
          <span className={`tabnum inline-flex items-center gap-1 ${toneClass(row.change_pct)}`}>
            {formatSignedPercent(row.change_pct)}
            {isLikelyCapitalAction(row.change_pct) && (
              <span title={CAPITAL_ACTION_NOTE} className="text-warn" aria-label="Sermaye işlemi">
                ⚑
              </span>
            )}
          </span>
        ),
      },
      {
        key: 'free_float',
        label: 'Halka açık',
        width: '104px',
        align: 'right',
        title:
          'Fiilen işlem görebilen pay oranı — dar bir halka açıklık, küçük bir akışın fiyatı çok oynatması demek',
        sortValue: (row) => row.free_float_pct,
        render: (row) => <span className="tabnum">{formatPercent(row.free_float_pct)}</span>,
      },
      {
        key: 'relvol',
        label: 'Nispi hacim',
        width: '104px',
        align: 'right',
        title: 'Bugünkü hacmin kendi 10 günlük ortalamasına oranı',
        sortValue: (row) => row.relative_volume,
        render: (row) => (
          <span className={`tabnum ${(row.relative_volume ?? 0) > 1.5 ? 'text-warn' : ''}`}>
            {formatNumber(row.relative_volume, 2)}×
          </span>
        ),
      },
      {
        key: 'range',
        label: '52h konumu',
        width: '124px',
        align: 'right',
        title: '0 = yıllık dip, 1 = yıllık zirve',
        sortValue: (row) => row.range_position,
        render: (row) => <RangeBar position={row.range_position} />,
      },
      {
        key: 'rsi',
        label: 'RSI',
        width: '76px',
        align: 'right',
        title: '14 günlük göreli güç endeksi. 30 altı aşırı satım, 70 üstü aşırı alım.',
        sortValue: (row) => row.rsi,
        render: (row) => (
          <span
            className={`tabnum ${
              row.rsi === null ? '' : row.rsi >= 70 ? 'text-up' : row.rsi <= 30 ? 'text-down' : ''
            }`}
          >
            {formatNumber(row.rsi, 0)}
          </span>
        ),
      },
      {
        key: 'crowding',
        label: 'Kalabalıklık',
        width: '104px',
        align: 'right',
        title:
          'Nispi hacim / halka açıklık. Sıralama yardımcısıdır, bir hüküm değil. Halka açıklığı %5’in altındaki veya hacmi yükselmemiş hisseler puanlanmaz.',
        sortValue: (row) => row.crowding,
        render: (row) => <span className="tabnum">{formatNumber(row.crowding, 1)}</span>,
      },
      {
        key: 'oi_change',
        label: 'AP değişim',
        width: '104px',
        align: 'right',
        title: 'Vadeli açık pozisyondaki günlük değişim, tüm vadeler toplanmış',
        sortValue: (row) => row.open_interest_change,
        render: (row) => (
          <span className={`tabnum ${toneClass(row.open_interest_change)}`}>
            {row.open_interest_change === null
              ? '—'
              : `${row.open_interest_change > 0 ? '+' : ''}${formatCompact(row.open_interest_change, 1)}`}
          </span>
        ),
      },
      {
        key: 'market_cap',
        label: 'Piyasa değeri',
        width: '116px',
        align: 'right',
        sortValue: (row) => row.market_cap,
        render: (row) => <span className="tabnum">{formatCompactTry(row.market_cap)}</span>,
      },
    ],
    []
  );

  if (isError && !data) {
    return (
      <BistPageShell
        title="Konumlanma"
        description="Halka açıklık, olağandışı hacim, yıllık konum ve vadeli pozisyon."
        delayed
      >
        <StatusMessage
          icon={AlertTriangle}
          action={
            <button
              type="button"
              onClick={() => refetch()}
              className="rounded-md border border-line px-3 py-1 text-sm text-fg transition-colors hover:border-line-strong"
            >
              Tekrar dene
            </button>
          }
        >
          Konumlanma verisi alınamadı.
        </StatusMessage>
      </BistPageShell>
    );
  }

  const nearLabel = `yıllık aralığın ${formatPercent(NEAR_EXTREME, 0)}’lik ucunda`;

  return (
    <BistPageShell
      title="Konumlanma"
      description="Halka açıklık, olağandışı hacim, yıllık konum ve vadeli pozisyon."
      delayed
      action={
        <button
          type="button"
          onClick={() => refetch()}
          aria-label="Yenile"
          className="rounded-md p-1 text-fg-subtle transition-colors hover:text-fg"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
        </button>
      }
    >
      <StaleStrip
        stale={data?.stale}
        refreshFailed={isError && !!data}
        asOf={data?.as_of}
        onRetry={() => refetch()}
      />

      <BistPositioningNote data={note.data} isLoading={note.isLoading} />

      {/* The caveat stays on the page — it is the difference between what this
          board was promised as and what it is. It no longer costs four lines of
          the fold to say so. */}
      <details className="surface surface-flat group px-3 py-2 text-2xs text-fg-muted">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 transition-colors marker:content-none hover:text-fg">
          <ChevronRight
            className="h-3 w-3 shrink-0 text-fg-subtle transition-transform group-open:rotate-90"
            aria-hidden="true"
          />
          <span>
            Bu sayfa <strong className="text-fg">yayımlanmış</strong> konumlanmayı gösterir —
            fonların hangi hisseyi tuttuğu neden burada değil?
          </span>
        </summary>
        <p className="mt-2 border-t border-line pt-2">
          Fonların portföylerini tersine çeviren bir görünüm hedeflenmişti. TEFAS 2026’daki API
          yenilemesinde portföy dağılımını kaldırdı ve KAP fon portföylerini yalnızca düz metin ek
          olarak yayımlıyor, dolayısıyla bu veri hiçbir kamuya açık uçtan alınamıyor. Buradaki her
          kolon gerçekten yayımlanan bir büyüklüktür.
        </p>
      </details>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricTile
          label="Kalabalıklaşan"
          value={isLoading ? '—' : summary.scored}
          note="ölçülebilir skor taşıyan hisse"
        />
        <MetricTile
          label="Zirveye yakın"
          value={isLoading ? '—' : summary.nearHigh}
          note={nearLabel}
          tone="text-up"
        />
        <MetricTile
          label="Dibe yakın"
          value={isLoading ? '—' : summary.nearLow}
          note={nearLabel}
          tone="text-down"
        />
        <MetricTile
          label="Vadeli açık pozisyon"
          value={isLoading ? '—' : formatSignedPercent(summary.openInterestGrowth)}
          note={
            summary.dominantQuadrant
              ? `ağırlık: ${QUADRANT_LABEL[summary.dominantQuadrant].toLocaleLowerCase('tr-TR')}`
              : 'baskın yön yok'
          }
        />
      </div>

      <FilterChips
        filter={filter}
        matched={filtered.length}
        total={rows.length}
        onChange={setFilter}
      />

      <div className="grid gap-3 lg:grid-cols-2">
        <BistChartPanel
          title="Kalabalıklaşma"
          legend="Yatay: halka açıklık · Dikey: nispi hacim · Balon: piyasa değeri · Renk: günlük değişim"
        >
          {isLoading ? (
            <div className="shimmer h-[300px]" />
          ) : (
            <CrowdingScatter points={points} onSelect={openStock} />
          )}
        </BistChartPanel>

        <BistChartPanel
          title="Vadeli konumlanma"
          legend="Yatay: açık pozisyonun oransal değişimi · Dikey: fiyat · Dolu: pozisyon açılıyor · İçi boş: kapanıyor · Balon: açık pozisyon büyüklüğü. Yalnızca hisse bazlı sözleşmeler; endeks ve döviz vadelileri bu panoda yer almaz."
          action={
            data && !data.has_futures_data ? (
              <span className="label text-warn">VİOP verisi alınamadı</span>
            ) : undefined
          }
        >
          {isLoading ? (
            <div className="shimmer h-[300px]" />
          ) : (
            <FuturesQuadrant
              points={forQuadrant}
              selected={filter.quadrant}
              onSelectQuadrant={(quadrant) => setFilter({ ...filter, quadrant })}
              onSelectTicker={openStock}
            />
          )}
        </BistChartPanel>

        <BistChartPanel
          title="Yıllık konum dağılımı"
          legend="Yükseklik: hisse sayısı · Renk: o dilimin medyan RSI’ı"
        >
          {isLoading ? (
            <div className="shimmer h-[200px]" />
          ) : (
            <RangeDistribution
              buckets={forRange}
              selected={filter.rangeBucket}
              onSelect={(rangeBucket) => setFilter({ ...filter, rangeBucket })}
            />
          )}
        </BistChartPanel>

        <BistChartPanel
          title="Sektör ısısı"
          legend="Alan: sektördeki toplam kalabalıklık · Renk: medyan nispi hacim"
        >
          {isLoading ? (
            <div className="shimmer h-[200px]" />
          ) : (
            <SectorCrowdingMap
              sectors={forSectors}
              selected={filter.sector}
              onSelect={(sector) => setFilter({ ...filter, sector })}
            />
          )}
        </BistChartPanel>
      </div>

      <details open className="surface surface-flat overflow-hidden">
        <summary className="flex cursor-pointer items-center justify-between gap-3 border-b border-line px-3 py-2 text-base font-semibold text-fg">
          Tüm hisseler
          <span className="label">{filtered.length} kayıt</span>
        </summary>
        <DataTable
          columns={columns}
          rows={filtered}
          rowKey={(row) => row.ticker}
          onRowClick={(row) => openStock(row.ticker)}
          isLoading={isLoading}
          initialSort={{ key: 'crowding', direction: 'desc' }}
          emptyMessage="Bu filtreyle eşleşen hisse yok."
        />
      </details>
    </BistPageShell>
  );
}
