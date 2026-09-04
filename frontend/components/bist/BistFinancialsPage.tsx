'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import BistChartPanel from '@/components/bist/BistChartPanel';
import MetricTile from '@/components/bist/MetricTile';
import BistPageShell from '@/components/bist/BistPageShell';
import AbsentPanel from '@/components/bist/financials/AbsentPanel';
import BalanceLines from '@/components/bist/financials/BalanceLines';
import BasisToggle from '@/components/bist/financials/BasisToggle';
import CashBridge from '@/components/bist/financials/CashBridge';
import DebtStack from '@/components/bist/financials/DebtStack';
import EarningsLadder from '@/components/bist/financials/EarningsLadder';
import FinancialsNote from '@/components/bist/financials/FinancialsNote';
import MarginLines from '@/components/bist/financials/MarginLines';
import RealNominalScissors from '@/components/bist/financials/RealNominalScissors';
import SeasonalGrid from '@/components/bist/financials/SeasonalGrid';
import TickerPicker from '@/components/bist/financials/TickerPicker';
import DataTable, { type ColumnDef } from '@/components/ui/DataTable';
import StatusMessage from '@/components/ui/StatusMessage';
import { useBistFinancials, useBistFinancialsNote } from '@/hooks/useBist';
import type { BistFinancials, BistQuarter } from '@/lib/bist-api';
import {
  type Basis,
  absentCopy,
  chartState,
  effectiveBasis,
  FIELD_LABELS,
  metricTiles,
  unitFor,
} from '@/lib/bist-financials';
import { EMPTY, formatCompact, formatDateTime } from '@/lib/bist-format';

const DEFAULT_TICKER = 'THYAO';

/** The bar-and-lines panel differs per chart of accounts rather than emptying. */
function ladderFor(payload: BistFinancials) {
  if (payload.layout === 'insurance') {
    return { title: 'Net kâr', bar: 'net_income', lines: [] as string[] };
  }
  if (payload.layout === 'bank') {
    return {
      title: 'Gelir merdiveni',
      bar: 'revenue',
      lines: ['operating_profit', 'net_income'],
    };
  }
  return {
    title: 'Gelir merdiveni',
    bar: 'revenue',
    lines: ['gross_profit', 'ebitda', 'net_income'],
  };
}

/** Whichever headline line this company actually has, for the two DOM panels. */
function headlineField(payload: BistFinancials): string {
  return payload.available_fields.includes('revenue') ? 'revenue' : 'net_income';
}

function quarterColumns(payload: BistFinancials, basis: Basis): ColumnDef<BistQuarter>[] {
  const values = payload.quarters.flatMap((quarter) =>
    payload.available_fields.map((field) =>
      basis === 'real' ? (quarter.real?.[field] ?? null) : quarter.nominal[field]
    )
  );
  const unit = unitFor(values);

  const read = (quarter: BistQuarter, field: string) =>
    basis === 'real' ? (quarter.real?.[field] ?? null) : quarter.nominal[field];

  return [
    {
      key: 'period',
      label: 'Dönem',
      width: '90px',
      sortValue: (row) => row.period,
      render: (row) => (
        <span className="text-fg">
          {row.period}
          {row.provisional && (
            <span className="ml-1 text-warn" title="Kendi ayının TÜFE'si henüz açıklanmadı.">
              *
            </span>
          )}
        </span>
      ),
    },
    // Columns follow what this company reported, so a bank's table has five and
    // an industrial's has seventeen. A fixed column set would fill most of a
    // bank's table with dashes and read as missing data rather than as a
    // different chart of accounts.
    ...payload.available_fields.map<ColumnDef<BistQuarter>>((field) => ({
      key: field,
      label: `${FIELD_LABELS[field] ?? field} (${unit.label})`,
      width: 'minmax(120px, 1fr)',
      align: 'right' as const,
      sortValue: (row) => read(row, field),
      render: (row) => {
        const value = read(row, field);
        return value == null ? EMPTY : formatCompact(value / unit.divisor, 1);
      },
    })),
  ];
}

export default function BistFinancialsPage() {
  const [ticker, setTicker] = useState(DEFAULT_TICKER);
  const [requested, setRequested] = useState<Basis>('real');

  const { data, isLoading, isError, isFetching, refetch } = useBistFinancials(ticker);
  const note = useBistFinancialsNote(ticker);

  // The frame actually drawn, which is not always the one asked for. Reading it
  // once here keeps every panel below on the same footing.
  const basis = effectiveBasis(requested, data?.deflation);
  const ladder = ladderFor(data ?? ({} as BistFinancials));
  const field = data ? headlineField(data) : 'revenue';

  return (
    <BistPageShell
      title="Bilanço"
      description="Çeyreklik finansal tablolar, enflasyondan arındırılmış."
      action={
        <div className="flex items-center gap-2">
          <TickerPicker value={ticker} onChange={setTicker} />
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Yenile"
            className="rounded-md p-1 text-fg-subtle transition-colors hover:text-fg"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
        </div>
      }
    >
      {isError && !data ? (
        <div className="surface">
          <StatusMessage icon={AlertTriangle}>
            {ticker} için finansal tablo bulunamadı. İş Yatırım bu kod altında tablo yayımlamıyor
            olabilir.
          </StatusMessage>
        </div>
      ) : isLoading && !data ? (
        <div className="surface">
          <StatusMessage icon={RefreshCw}>Tablolar yükleniyor…</StatusMessage>
        </div>
      ) : data ? (
        <>
          <FinancialsNote payload={data} note={note.data?.note} isLoading={note.isLoading} />

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {metricTiles(data, basis).map((tile) => (
              <MetricTile key={tile.label} {...tile} />
            ))}
          </div>

          <div className="surface surface-flat px-3 py-2">
            <BasisToggle deflation={data.deflation} basis={requested} onChange={setRequested} />
          </div>

          <div className="grid gap-2 xl:grid-cols-2">
            <BistChartPanel
              title={ladder.title}
              legend={`Çubuk ${FIELD_LABELS[ladder.bar]}, çizgiler kâr kalemleri · ${
                basis === 'real' ? 'reel' : 'nominal'
              }`}
            >
              <EarningsLadder
                payload={data}
                basis={basis}
                barField={ladder.bar}
                lineFields={ladder.lines}
              />
            </BistChartPanel>

            <BistChartPanel
              title="Marj bandı"
              legend="Son 4 çeyrek marjları · marj bir orandır, enflasyon sadeleşir, iki görünümde de aynıdır"
            >
              {chartState(data, ['revenue', 'net_income']) === 'present' ? (
                <MarginLines payload={data} />
              ) : (
                <AbsentPanel>{absentCopy(data, ['revenue', 'net_income'])}</AbsentPanel>
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Kâr nakde dönüyor mu"
              legend="Çubuklar faaliyet nakit akışı ve net kâr, çizgi ikisinin oranı"
            >
              {chartState(data, ['ocf', 'net_income']) === 'present' ? (
                <CashBridge payload={data} basis={basis} />
              ) : (
                <AbsentPanel>{absentCopy(data, ['ocf', 'net_income'])}</AbsentPanel>
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Borç ve nakit"
              legend="Yığın vade kırılımı, çizgiler nakit ve net borç/FAVÖK"
            >
              {chartState(data, ['total_debt', 'short_term_debt']) === 'present' ? (
                <DebtStack payload={data} basis={basis} />
              ) : (
                <AbsentPanel>{absentCopy(data, ['total_debt', 'short_term_debt'])}</AbsentPanel>
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Özkaynak, varlıklar ve kârlılık"
              legend={`Bilanço ölçeği · ${basis === 'real' ? 'reel' : 'nominal'} · kesikli çizgi ROE`}
            >
              {chartState(data, ['equity', 'total_assets']) === 'present' ? (
                <BalanceLines payload={data} basis={basis} />
              ) : (
                <AbsentPanel>{absentCopy(data, ['equity', 'total_assets'])}</AbsentPanel>
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Reel–nominal makası"
              legend="Gri çubuk kaç lira, renkli çubuk o liranın ne aldığı"
            >
              {data.deflation.available ? (
                <RealNominalScissors payload={data} field={field} />
              ) : (
                <AbsentPanel>
                  {`Bu sayfada enflasyon düzeltmesi uygulanamadı, bu yüzden karşılaştırılacak ikinci bir seri yok. ${
                    data.deflation.reason === 'cpi_key_missing'
                      ? 'TCMB EVDS anahtarı tanımlı değil.'
                      : data.deflation.reason === 'cpi_unavailable'
                        ? 'TCMB fiyat endeksine ulaşılamıyor.'
                        : 'Fiyat endeksi bu şirketin en yeni çeyreğine ulaşmıyor.'
                  }`}
                </AbsentPanel>
              )}
            </BistChartPanel>
          </div>

          <BistChartPanel
            title="Çeyrek mevsimselliği"
            legend={`Satır yıl, sütun çeyrek · ${basis === 'real' ? 'reel' : 'nominal'}`}
          >
            {data.quarters.length >= 6 ? (
              <SeasonalGrid payload={data} basis={basis} field={field} />
            ) : (
              <AbsentPanel>
                {`Mevsimsellik ızgarası için en az altı çeyrek gerekiyor; bu tahtada ${data.quarters.length} çeyrek var.`}
              </AbsentPanel>
            )}
          </BistChartPanel>

          <div className="surface surface-flat overflow-hidden">
            <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-3 py-2">
              <h2 className="text-sm text-fg">Çeyrekler</h2>
              <span className="text-2xs text-fg-subtle">
                Kaynak: İş Yatırım · çekildi {formatDateTime(data.fetched_at)}
                {data.deflation.provisional_periods.length > 0 && ' · * geçici çevrim'}
              </span>
            </div>
            <DataTable
              columns={quarterColumns(data, basis)}
              rows={data.quarters}
              rowKey={(row) => row.period}
            />
          </div>
        </>
      ) : null}
    </BistPageShell>
  );
}
