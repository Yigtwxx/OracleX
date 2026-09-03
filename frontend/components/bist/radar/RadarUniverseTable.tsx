'use client';

import { useRouter } from 'next/navigation';
import { useMemo } from 'react';

import DataTable, { type ColumnDef } from '@/components/ui/DataTable';
import type { RadarRow } from '@/lib/bist-api';
import { EMPTY, formatSignedPercent, formatTry, toneClass } from '@/lib/bist-format';
import { STAGE_LABEL, formatRr, rejectionText, scoreTone } from '@/lib/bist-radar';

/**
 * Every XU100 member and where it stopped.
 *
 * The answer to "why is X not on the list": the stage it reached and the one
 * rule that ended it. Sorted by total score so the near misses sit at the top,
 * with the names the trend filter dropped — which have no score at all — last.
 */
export default function RadarUniverseTable({ rows }: { rows: RadarRow[] }) {
  const router = useRouter();

  const columns = useMemo<ColumnDef<RadarRow>[]>(
    () => [
      {
        key: 'ticker',
        label: 'Hisse',
        width: 'minmax(150px, 1.4fr)',
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
        width: '100px',
        align: 'right',
        sortValue: (row) => row.price,
        render: (row) => <span className="tabnum">{formatTry(row.price)}</span>,
      },
      {
        key: 'change',
        label: 'Değişim',
        width: '90px',
        align: 'right',
        sortValue: (row) => row.change_pct,
        render: (row) => (
          <span className={`tabnum ${toneClass(row.change_pct)}`}>
            {formatSignedPercent(row.change_pct)}
          </span>
        ),
      },
      {
        key: 'stage',
        label: 'Aşama',
        width: '110px',
        sortValue: (row) => row.stage_reached,
        render: (row) => (
          <span className="text-2xs text-fg-muted">{STAGE_LABEL[row.stage_reached]}</span>
        ),
      },
      {
        key: 'reason',
        label: 'Sonuç',
        width: 'minmax(160px, 1.6fr)',
        sortValue: (row) => rejectionText(row),
        render: (row) => (
          <span
            className={`truncate text-2xs ${
              row.stage_reached === 'candidate'
                ? 'text-up'
                : row.vetoes.length
                  ? 'text-down'
                  : 'text-fg-muted'
            }`}
            title={row.vetoes.map((v) => v.label).join(', ') || undefined}
          >
            {rejectionText(row)}
            {row.vetoes.length > 1 ? ` +${row.vetoes.length - 1}` : ''}
          </span>
        ),
      },
      {
        key: 'technical',
        label: 'Teknik',
        width: '80px',
        align: 'right',
        sortValue: (row) => row.score_technical,
        render: (row) => (
          <span className={`tabnum ${scoreTone(row.score_technical)}`}>
            {row.score_technical ?? EMPTY}
          </span>
        ),
      },
      {
        key: 'fundamental',
        label: 'Temel',
        width: '80px',
        align: 'right',
        title: 'Temel puan; mali tablo okunamadıysa yalnızca çarpanlara dayanır',
        sortValue: (row) => row.score_fundamental,
        render: (row) => (
          <span className={`tabnum ${scoreTone(row.score_fundamental)}`}>
            {row.score_fundamental ?? EMPTY}
            {row.fundamental_depth === 'ratios_only' && row.score_fundamental !== null ? '*' : ''}
          </span>
        ),
      },
      {
        key: 'total',
        label: 'Toplam',
        width: '80px',
        align: 'right',
        sortValue: (row) => row.score_total,
        render: (row) => (
          <span className={`tabnum font-medium ${scoreTone(row.score_total)}`}>
            {row.score_total ?? EMPTY}
          </span>
        ),
      },
      {
        key: 'rr',
        label: 'Ö/R',
        width: '70px',
        align: 'right',
        title: 'Ödül / risk',
        sortValue: (row) => row.rr,
        render: (row) => <span className="tabnum">{formatRr(row.rr)}</span>,
      },
    ],
    []
  );

  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={(row) => row.ticker}
      onRowClick={(row) => router.push(`/bist/hisseler/${row.ticker}`)}
      initialSort={{ key: 'total', direction: 'desc' }}
      pageSize={100}
      emptyMessage="Evren boş."
    />
  );
}
