'use client';

import { AlertTriangle, RefreshCw, Search, X } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import DataTable, { type ColumnDef } from '@/components/ui/DataTable';
import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup from '@/components/ui/ToggleGroup';
import { useBistMarketNote, useBistOverview, useBistStocks } from '@/hooks/useBist';
import type { BistStock } from '@/lib/bist-api';
import {
  CAPITAL_ACTION_NOTE,
  EMPTY,
  formatCompactTry,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  formatTry,
  isLikelyCapitalAction,
  toneClass,
  turkishIncludes,
} from '@/lib/bist-format';
import BistMarketNote from './BistMarketNote';
import BistPageShell from './BistPageShell';
import BistRibbon from './BistRibbon';
import ReturnCell from './ReturnCell';

/**
 * The index filters, in the order a reader reaches for them.
 *
 * `XUTUM` is "everything listed", which is what the unfiltered board already
 * shows, so it is absent rather than duplicated as a fifth button.
 */
const INDEX_OPTIONS = [
  { value: '', label: 'Tümü' },
  { value: 'XU100', label: 'XU100' },
  { value: 'XU030', label: 'XU030' },
  { value: 'XU050', label: 'XU050' },
  { value: 'XBANK', label: 'Banka' },
] as const;

type IndexFilter = (typeof INDEX_OPTIONS)[number]['value'];

const numeric = (value: number | null) => value;

export default function BistStocksPage() {
  const router = useRouter();
  const [index, setIndex] = useState<IndexFilter>('XU100');
  const [sector, setSector] = useState('');
  const [search, setSearch] = useState('');

  // Only for the ribbon. Shares `useBistOverview`'s query key with the landing
  // board, so arriving here from it costs no second request.
  const { data: overview } = useBistOverview();

  // Not parameterised by the filters above. The read is whether the index and
  // the breadth agree, which is a property of the whole board — a per-filter
  // version would answer a question nobody asked and multiply the note cache by
  // every combination of index and sector.
  const marketNote = useBistMarketNote();

  // The index and sector filters go to the server so the payload stays small;
  // search is applied here because it is per-keystroke and the board is already
  // in memory. Filtering server-side would mean a request per character.
  const { data, isLoading, isError, isFetching, refetch } = useBistStocks({
    index: index || undefined,
    sector: sector || undefined,
    sort_by: 'market_cap',
    limit: 1000,
  });

  const rows = useMemo(() => {
    const all = data?.stocks ?? [];
    const needle = search.trim();
    if (!needle) return all;
    return all.filter(
      (row) => turkishIncludes(row.ticker, needle) || turkishIncludes(row.name, needle)
    );
  }, [data, search]);

  const realAvailable = !!data?.real_return?.deflatable_windows.includes('1y');

  const columns = useMemo<ColumnDef<BistStock>[]>(
    () => [
      {
        key: 'ticker',
        label: 'Hisse',
        width: 'minmax(150px, 1.6fr)',
        sortValue: (row) => row.ticker,
        render: (row) => (
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate font-medium text-fg">{row.ticker}</span>
            <span className="truncate text-2xs text-fg-subtle">{row.name}</span>
          </span>
        ),
      },
      {
        key: 'price',
        label: 'Fiyat',
        width: '110px',
        align: 'right',
        sortValue: (row) => numeric(row.price),
        render: (row) => <span className="tabnum">{formatTry(row.price)}</span>,
      },
      {
        key: 'change',
        label: 'Değişim',
        width: '110px',
        align: 'right',
        sortValue: (row) => numeric(row.change_pct),
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
        key: 'return1y',
        label: '1Y getiri',
        width: '110px',
        align: 'right',
        title: realAvailable
          ? 'Üst satır nominal, alt satır enflasyona göre reel getiri'
          : 'Nominal getiri — enflasyon serisi alınamadı',
        sortValue: (row) => numeric(row.returns['1y']?.nominal ?? null),
        render: (row) => <ReturnCell framed={row.returns['1y']} realAvailable={realAvailable} />,
      },
      {
        key: 'market_cap',
        label: 'Piyasa değeri',
        width: '130px',
        align: 'right',
        sortValue: (row) => numeric(row.market_cap),
        render: (row) => <span className="tabnum">{formatCompactTry(row.market_cap)}</span>,
      },
      {
        key: 'traded_value',
        label: 'İşlem hacmi',
        width: '120px',
        align: 'right',
        sortValue: (row) => numeric(row.traded_value),
        render: (row) => <span className="tabnum">{formatCompactTry(row.traded_value)}</span>,
      },
      {
        key: 'pe',
        label: 'F/K',
        width: '90px',
        align: 'right',
        title: 'Fiyat / Kazanç',
        sortValue: (row) => numeric(row.pe),
        render: (row) => <span className="tabnum">{formatNumber(row.pe, 1)}</span>,
      },
      {
        key: 'pb',
        label: 'PD/DD',
        width: '90px',
        align: 'right',
        title: 'Piyasa değeri / Defter değeri',
        sortValue: (row) => numeric(row.pb),
        render: (row) => <span className="tabnum">{formatNumber(row.pb, 2)}</span>,
      },
      {
        key: 'ev_ebitda',
        label: 'FD/FAVÖK',
        width: '100px',
        align: 'right',
        title: 'Firma değeri / FAVÖK',
        sortValue: (row) => numeric(row.ev_ebitda),
        render: (row) => <span className="tabnum">{formatNumber(row.ev_ebitda, 1)}</span>,
      },
      {
        key: 'free_float',
        label: 'Halka açık',
        width: '100px',
        align: 'right',
        title: 'Fiilen işlem görebilen pay oranı',
        sortValue: (row) => numeric(row.free_float_pct),
        render: (row) => <span className="tabnum">{formatPercent(row.free_float_pct)}</span>,
      },
      {
        key: 'sector',
        label: 'Sektör',
        width: 'minmax(120px, 1fr)',
        sortValue: (row) => row.sector || null,
        render: (row) => (
          <span className="truncate text-2xs text-fg-muted">{row.sector || EMPTY}</span>
        ),
      },
    ],
    [realAvailable]
  );

  const showColdError = isError && !data;

  return (
    <BistPageShell
      title="Hisseler"
      description="Borsa İstanbul şirketleri, çarpanlar ve enflasyona göre reel getiri."
      delayed
      ribbon={
        overview ? (
          <BistRibbon sentiment={overview.sentiment} dominance={overview.dominance} />
        ) : undefined
      }
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

      <BistMarketNote data={marketNote.data} isLoading={marketNote.isLoading} />

      <div className="surface surface-flat flex min-h-0 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
          <ToggleGroup
            label="Endeks"
            options={INDEX_OPTIONS.map((option) => ({ ...option }))}
            value={index}
            onChange={(next) => setIndex(next)}
          />

          <select
            value={sector}
            onChange={(event) => setSector(event.target.value)}
            aria-label="Sektör"
            className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-fg-muted transition-colors hover:text-fg"
          >
            <option value="">Tüm sektörler</option>
            {(data?.sectors ?? []).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>

          <div role="search" className="ml-auto flex items-center gap-1.5">
            <Search className="h-3.5 w-3.5 text-fg-subtle" aria-hidden="true" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => event.key === 'Escape' && setSearch('')}
              placeholder="Kod veya şirket ara"
              aria-label="Hisse ara"
              className="w-44 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch('')}
                aria-label="Aramayı temizle"
                className="text-fg-subtle transition-colors hover:text-fg"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          <span className="label shrink-0">
            {rows.length} / {data?.total ?? 0}
          </span>
        </div>

        {showColdError ? (
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
            Hisse listesi alınamadı.
          </StatusMessage>
        ) : (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.ticker}
            onRowClick={(row) => router.push(`/bist/hisseler/${row.ticker}`)}
            isLoading={isLoading}
            initialSort={{ key: 'market_cap', direction: 'desc' }}
            emptyMessage={
              search ? `"${search}" için sonuç yok.` : 'Bu filtrelerle eşleşen hisse yok.'
            }
          />
        )}
      </div>

      {data?.real_return && !data.real_return.deflatable_windows.includes('1y') && (
        <p className="text-2xs text-fg-subtle">
          Reel getiri kolonu şu anda hesaplanamıyor — enflasyon serisi alınamadı.
        </p>
      )}
    </BistPageShell>
  );
}
