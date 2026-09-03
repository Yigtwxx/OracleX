'use client';

import { AlertTriangle, RefreshCw, Search, X } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import DataTable, { type ColumnDef } from '@/components/ui/DataTable';
import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup from '@/components/ui/ToggleGroup';
import { useBistFunds, useBistFundsMarketNote, useBistOverview } from '@/hooks/useBist';
import type { BistFund } from '@/lib/bist-api';
import { EMPTY, formatPercent, turkishIncludes } from '@/lib/bist-format';
import { allocationSegments, allocationTotal, equityWeight } from '@/lib/fund-allocation';
import BistFundsMarketNote from './BistFundsMarketNote';
import FundAllocationBar from './FundAllocationBar';
import BistFundsRibbon from './BistFundsRibbon';
import BistPageShell from './BistPageShell';
import ReturnCell from './ReturnCell';

const FUND_TYPES = [
  { value: 'YAT', label: 'Yatırım' },
  { value: 'EMK', label: 'Emeklilik' },
  { value: 'BYF', label: 'Borsa (BYF)' },
] as const;

type FundType = (typeof FUND_TYPES)[number]['value'];

/** TEFAS's own 1–7 grade. Coloured, because "risk 7" should not read as neutral. */
function RiskBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-fg-subtle">{EMPTY}</span>;
  const tone = value >= 6 ? 'text-down' : value >= 4 ? 'text-warn' : 'text-up';
  return (
    <span className={`tabnum ${tone}`} title={`TEFAS risk değeri: ${value}/7`}>
      {value}
    </span>
  );
}

export default function BistFundsPage() {
  const router = useRouter();
  const [fundType, setFundType] = useState<FundType>('YAT');
  const [umbrella, setUmbrella] = useState('');
  const [search, setSearch] = useState('');

  // Only for the fear & greed reading, which is an equity measure the fund
  // board borrows rather than recomputes. Same query key as every other board,
  // so it is one cached request rather than a per-page one.
  const { data: overview } = useBistOverview();

  // Keyed on the fund type: Yatırım, Emeklilik and BYF are different universes
  // with different mandates, so one median across all three would describe none
  // of them. Switching the toggle switches the read.
  const marketNote = useBistFundsMarketNote(fundType);

  const { data, isLoading, isError, isFetching, refetch } = useBistFunds({
    fund_type: fundType,
    umbrella: umbrella || undefined,
    sort_by: '1y',
    limit: 2000,
  });

  const rows = useMemo(() => {
    const all = data?.funds ?? [];
    const needle = search.trim();
    if (!needle) return all;
    return all.filter(
      (row) => turkishIncludes(row.code, needle) || turkishIncludes(row.title, needle)
    );
  }, [data, search]);

  const deflatable = useMemo(() => data?.real_return?.deflatable_windows ?? [], [data]);

  // The bucket vocabulary arrives once on the response rather than on every
  // row, so it is turned into a lookup once rather than per cell.
  const bucketLabels = useMemo(() => {
    const entries = data?.allocation?.buckets ?? [];
    return Object.fromEntries(entries.map((bucket) => [bucket.key, bucket.label]));
  }, [data]);

  const columns = useMemo<ColumnDef<BistFund>[]>(() => {
    const window = (key: string, label: string): ColumnDef<BistFund> => {
      const hasReal = deflatable.includes(key);
      return {
        key,
        label,
        width: '104px',
        align: 'right',
        title: hasReal
          ? 'Üst satır nominal, alt satır enflasyona göre reel getiri'
          : 'Nominal getiri — bu dönem için enflasyon serisi yok',
        sortValue: (row) => row.returns[key] ?? null,
        render: (row) => <ReturnCell framed={row.framed_returns[key]} realAvailable={hasReal} />,
      };
    };

    return [
      {
        key: 'code',
        label: 'Fon',
        width: 'minmax(220px, 3fr)',
        sortValue: (row) => row.code,
        render: (row) => (
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate font-medium text-fg">{row.code}</span>
            <span className="truncate text-2xs text-fg-subtle">{row.title}</span>
          </span>
        ),
      },
      window('1a', '1 ay'),
      window('3a', '3 ay'),
      window('6a', '6 ay'),
      window('yb', 'Yılbaşı'),
      window('1y', '1 yıl'),
      window('3y', '3 yıl'),
      {
        key: 'umbrella',
        label: 'Şemsiye',
        width: 'minmax(150px, 1fr)',
        // Centred rather than left-aligned: this is the widest flexible column
        // on the board and the shortest content in it, so hugging the left
        // edge piles all the slack against the risk grade on the right.
        align: 'center',
        sortValue: (row) => row.umbrella || null,
        render: (row) => (
          <span className="truncate text-2xs text-fg-muted">{row.umbrella || EMPTY}</span>
        ),
      },
      {
        key: 'allocation',
        label: 'Dağılım',
        width: '96px',
        // Sorted on equity weight, and the header says so: a stacked bar has no
        // natural scalar, and a sort whose basis is invisible is worse than no
        // sort at all. "How much of this is stocks" is the axis a screener
        // reader is already on — it orders the board from money market to pure
        // equity in one click.
        title: 'TEFAS portföy dağılımı — hisse ağırlığına göre sıralanır',
        sortValue: (row) => equityWeight(row.allocation),
        render: (row) => (
          <FundAllocationBar
            segments={allocationSegments(row.allocation, bucketLabels)}
            total={allocationTotal(row.allocation)}
          />
        ),
      },
      {
        key: 'risk',
        label: 'Risk',
        width: '70px',
        align: 'right',
        sortValue: (row) => row.risk_value,
        render: (row) => <RiskBadge value={row.risk_value} />,
      },
    ];
  }, [deflatable, bucketLabels]);

  const showColdError = isError && !data;

  return (
    <BistPageShell
      title="Fonlar"
      description="TEFAS fon taraması — getiri sıralamasının söylemediğiyle birlikte."
      ribbon={
        data ? <BistFundsRibbon funds={data} sentiment={overview?.sentiment ?? null} /> : undefined
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
      <StaleStrip stale={data?.stale} refreshFailed={isError && !!data} onRetry={() => refetch()} />

      <BistFundsMarketNote data={marketNote.data} isLoading={marketNote.isLoading} />

      <div className="surface surface-flat flex min-h-0 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
          <ToggleGroup
            label="Fon tipi"
            options={FUND_TYPES.map((option) => ({ ...option }))}
            value={fundType}
            onChange={(next) => {
              setFundType(next);
              setUmbrella('');
            }}
          />

          <select
            value={umbrella}
            onChange={(event) => setUmbrella(event.target.value)}
            aria-label="Şemsiye fon türü"
            className="rounded-md border border-line bg-surface px-2 py-1 text-sm text-fg-muted transition-colors hover:text-fg"
          >
            <option value="">Tüm şemsiyeler</option>
            {(data?.umbrellas ?? []).map((name) => (
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
              placeholder="Fon kodu veya adı"
              aria-label="Fon ara"
              className="w-48 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
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
            TEFAS fon listesi alınamadı.
          </StatusMessage>
        ) : (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.code}
            onRowClick={(row) => router.push(`/bist/fonlar/${row.code}`)}
            isLoading={isLoading}
            initialSort={{ key: '1y', direction: 'desc' }}
            emptyMessage={
              search ? `"${search}" için sonuç yok.` : 'Bu filtrelerle eşleşen fon yok.'
            }
          />
        )}
      </div>

      <div className="space-y-1 text-2xs text-fg-subtle">
        {/* Which columns carry a real return, said once instead of drawn as an
            em dash on every cell that does not. */}
        <p>
          {deflatable.length > 0
            ? `Reel getiri yalnızca ${deflatable.join(', ')} kolonunda hesaplanabiliyor; diğer dönemler için enflasyon serisi yok.`
            : 'Enflasyon serisi alınamadı — tüm kolonlar nominal.'}
        </p>
        {/* Said once, under the board, rather than as an em dash on thirteen
            hundred rows. The column stays in place either way — one that
            appeared and disappeared on refetch would reflow the whole table. */}
        {data && data.allocation === null && <p>Portföy dağılımı TEFAS&rsquo;tan alınamadı.</p>}
        {data?.allocation?.stale && (
          <p>Portföy dağılımı {data.allocation.as_of} tarihli kayıttan geliyor.</p>
        )}
        {/* The rate every Sharpe on the detail pages is measured against.
            Stated here rather than buried, because it is an estimate and a
            reader comparing it to a published figure needs to know that. */}
        {data?.risk_free_rate != null && (
          <p>
            Risksiz faiz {formatPercent(data.risk_free_rate)}
            {data.risk_free_source === 'money_market_median' &&
              ' — para piyasası fonlarının medyan yıllık getirisinden türetildi, TCMB politika faizinden değil.'}
          </p>
        )}
      </div>
    </BistPageShell>
  );
}
