'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useMemo, useState } from 'react';

import DataTable, { type ColumnDef } from '@/components/ui/DataTable';
import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import { useBistViop, useBistViopNote } from '@/hooks/useBist';
import type { ViopContract } from '@/lib/bist-api';
import {
  EMPTY,
  formatCompact,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  toneClass,
} from '@/lib/bist-format';
import type { Quadrant } from '@/lib/bist-positioning';
import {
  boardTotals,
  expiryStacks,
  frontShare,
  futuresOnly,
  quadrantPoints,
  termCurve,
  underlyingBars,
  viopQuadrantOf,
} from '@/lib/bist-viop';
import BistChartPanel from './BistChartPanel';
import BistPageShell from './BistPageShell';
import MetricTile from './MetricTile';
import ViopExpiryStack from './viop/ViopExpiryStack';
import ViopFilterChips from './viop/ViopFilterChips';
import ViopNote from './viop/ViopNote';
import ViopOpenInterestBars from './viop/ViopOpenInterestBars';
import ViopQuadrant from './viop/ViopQuadrant';
import ViopTermCurve from './viop/ViopTermCurve';

/** The instrument, for the one row type that is not a future. */
const KIND_LABEL: Record<'call' | 'put', string> = {
  call: 'alım opsiyonu',
  put: 'satım opsiyonu',
};

/** How many underlyings get their own band in the expiry split. */
const STACK_BANDS = 4;

/**
 * The derivatives board.
 *
 * Open interest is the column that justifies the page: it is the only place in
 * the Turkish market where positioning is published rather than inferred. It is
 * summed per underlying rather than shown per expiry wherever a reader is
 * asking "how big is the USDTRY position" — the near month alone understates it
 * by roughly half — and kept per contract wherever the question is *what
 * happened today*, because a strip routinely opens in its back month while the
 * front is closed out and summing the two deletes the roll.
 *
 * Four panels sit above the table because the table cannot answer any of the
 * four questions a derivatives reader arrives with. It has an "AP değişim"
 * column and no way to pair it with the price; a total and no way to see that
 * one contract is most of it; six rows of the same asset and no way to see the
 * curve between them; and a size that reads identically whether the book has
 * rolled or not.
 *
 * The bar chart and the quadrant are also the page's filter. Picking an
 * underlying narrows the table *and* points the curve at that strip, which is
 * the pairing a reader does by hand otherwise — the curve is the one panel that
 * can only ever show one name.
 */
export default function BistViopPage() {
  const { data, isLoading, isError, isFetching, refetch } = useBistViop();
  const { data: note, isLoading: noteLoading } = useBistViopNote();

  const [underlying, setUnderlying] = useState<string | undefined>();
  const [quadrant, setQuadrant] = useState<Quadrant | undefined>();

  const contracts = useMemo(() => data?.contracts ?? [], [data]);

  // Every panel below is a futures read, and the board is not futures-only:
  // roughly a fifth of its rows are options whose settlement is a premium
  // rather than a price. Filtered once here so the tiles and the four charts
  // can never end up counting different boards. The table keeps every row —
  // the options are on the exchange and a reader is entitled to see them, with
  // their instrument named.
  const futures = useMemo(() => futuresOnly(contracts), [contracts]);
  const options = contracts.length - futures.length;

  const bars = useMemo(() => underlyingBars(futures), [futures]);
  const points = useMemo(() => quadrantPoints(futures), [futures]);
  const totals = useMemo(() => boardTotals(futures), [futures]);

  // The curve can only draw one strip, so it falls back to the largest book
  // rather than to nothing: an empty panel until the reader clicks would make
  // the page look broken on arrival, and the largest book is the one a reader
  // opening this page is most likely to have come for.
  const curveFor = underlying ?? bars[0]?.underlying ?? '';
  const curve = useMemo(() => termCurve(futures, curveFor), [futures, curveFor]);

  const bands = useMemo(() => bars.slice(0, STACK_BANDS).map((bar) => bar.underlying), [bars]);
  const stacks = useMemo(() => expiryStacks(futures, bands), [futures, bands]);

  // Filtered from every row rather than from the futures, because the options
  // are on the exchange and the table is the one place that shows them. The
  // quadrant clause is the exception: it selects what the scatter drew, and the
  // scatter drew futures — a put whose premium rose as its open interest rose
  // is not "new money long", it is the opposite trade.
  const rows = useMemo(
    () =>
      contracts.filter(
        (contract) =>
          (underlying === undefined || contract.underlying === underlying) &&
          (quadrant === undefined ||
            (contract.kind === 'future' && viopQuadrantOf(contract) === quadrant))
      ),
    [contracts, underlying, quadrant]
  );

  const columns = useMemo<ColumnDef<ViopContract>[]>(
    () => [
      {
        key: 'contract',
        label: 'Sözleşme',
        width: 'minmax(180px, 1.6fr)',
        sortValue: (row) => row.contract,
        render: (row) => (
          <span className="flex min-w-0 flex-col leading-tight">
            <span className="truncate font-medium text-fg">{row.underlying}</span>
            <span className="truncate text-2xs text-fg-subtle">
              {row.expiry}
              {row.kind !== 'future' && ` · ${KIND_LABEL[row.kind]}`}
              {row.physical && ' · fiziki teslim'}
            </span>
          </span>
        ),
      },
      {
        key: 'last',
        label: 'Son',
        width: '110px',
        align: 'right',
        sortValue: (row) => row.last,
        render: (row) => <span className="tabnum">{formatNumber(row.last, 4)}</span>,
      },
      {
        key: 'change',
        label: 'Değişim',
        width: '100px',
        align: 'right',
        sortValue: (row) => row.change_pct,
        render: (row) => (
          <span className={`tabnum ${toneClass(row.change_pct)}`}>
            {formatSignedPercent(row.change_pct, 2)}
          </span>
        ),
      },
      {
        key: 'oi',
        label: 'Açık pozisyon',
        width: '130px',
        align: 'right',
        title: 'Kapatılmamış sözleşme sayısı',
        sortValue: (row) => row.open_interest,
        render: (row) => <span className="tabnum">{formatCompact(row.open_interest, 0)}</span>,
      },
      {
        key: 'oi_change',
        label: 'AP değişim',
        width: '120px',
        align: 'right',
        title: 'Açık pozisyondaki günlük değişim — pozisyon kurulumu mu, kapanışı mı',
        sortValue: (row) => row.open_interest_change,
        render: (row) => (
          <span className={`tabnum ${toneClass(row.open_interest_change)}`}>
            {row.open_interest_change === null
              ? EMPTY
              : `${row.open_interest_change > 0 ? '+' : ''}${formatCompact(row.open_interest_change, 0)}`}
          </span>
        ),
      },
      {
        key: 'settlement',
        label: 'Uzlaşma',
        width: '110px',
        align: 'right',
        sortValue: (row) => row.settlement,
        render: (row) => <span className="tabnum">{formatNumber(row.settlement, 4)}</span>,
      },
      {
        key: 'traded_at',
        label: 'Saat',
        width: '90px',
        align: 'right',
        render: (row) => <span className="tabnum text-2xs text-fg-subtle">{row.traded_at}</span>,
      },
    ],
    []
  );

  const showColdError = isError && !data;
  const front = frontShare(stacks);

  return (
    <BistPageShell
      title="VİOP"
      description="Vadeli işlem sözleşmeleri ve açık pozisyon."
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

      {showColdError ? (
        <div className="surface">
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
            VİOP tablosu okunamadı.
          </StatusMessage>
        </div>
      ) : (
        <>
          <ViopNote data={note} isLoading={noteLoading} />

          {data && (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <MetricTile
                label="Toplam açık pozisyon"
                value={formatCompact(totals.openInterest, 1)}
                title="Yalnızca vadeli sözleşmeler — opsiyon primi ile vadeli fiyatı aynı kitaba toplanamaz"
                note={
                  options === 0
                    ? `${futures.length} vadeli · ${bars.length} dayanak`
                    : `${futures.length} vadeli · ${bars.length} dayanak · ${options} opsiyon hariç`
                }
              />
              <MetricTile
                label="Günlük AP değişimi"
                value={
                  totals.changeRatio === null ? EMPTY : formatSignedPercent(totals.changeRatio, 2)
                }
                tone={toneClass(totals.change)}
                title="Dünkü kitaba göre — bugünkü toplama bölmek hareketin kendisini paydaya koyardı"
                note={`${totals.change > 0 ? '+' : ''}${formatCompact(totals.change, 1)} sözleşme`}
              />
              <MetricTile
                label="Yakın vadenin payı"
                value={formatPercent(front, 0)}
                title="Açık pozisyonun hâlâ en yakın vadede duran kısmı — tahtanın rollandığını gösteren tek okuma"
                note={stacks[0] ? `${stacks[0].label} · ${stacks.length} vade` : 'vade okunamadı'}
              />
              <MetricTile
                label="AP yayımlayan sözleşme"
                value={`${totals.measured}/${futures.length}`}
                title="Boş gelen açık pozisyon sütunu pozisyonsuzluk değil, okunamamış bir figürdür"
                note={
                  totals.silent === 0
                    ? 'tahtanın tamamı okundu'
                    : `${totals.silent} vadeli AP yayımlamadı`
                }
              />
            </div>
          )}

          <ViopFilterChips
            underlying={underlying}
            quadrant={quadrant}
            matched={rows.length}
            total={contracts.length}
            onClearUnderlying={() => setUnderlying(undefined)}
            onClearQuadrant={() => setQuadrant(undefined)}
            onClearAll={() => {
              setUnderlying(undefined);
              setQuadrant(undefined);
            }}
          />

          <div className="grid gap-3 lg:grid-cols-2">
            <BistChartPanel
              title="Açık pozisyon dağılımı"
              legend="Uzunluk: dayanağın tüm vadelerindeki toplam açık pozisyon · Renk: açık pozisyonun günlük yönü. Bir satıra tıklamak tabloyu ve vade eğrisini o dayanağa çevirir."
            >
              {isLoading ? (
                <div className="shimmer h-[300px]" />
              ) : (
                <ViopOpenInterestBars bars={bars} selected={underlying} onSelect={setUnderlying} />
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Kim açtı, kim kapattı"
              legend="Yatay: açık pozisyonun dünkü kitaba göre değişimi · Dikey: fiyat · Dolu: pozisyon açılıyor · İçi boş: kapanıyor · Balon: açık pozisyon büyüklüğü. Vade bazında — bir strip ön vadesini kapatırken arka vadesinde açılabilir."
            >
              {isLoading ? (
                <div className="shimmer h-[300px]" />
              ) : (
                <ViopQuadrant
                  points={points}
                  selected={quadrant}
                  onSelectQuadrant={setQuadrant}
                  onSelectUnderlying={setUnderlying}
                />
              )}
            </BistChartPanel>

            <BistChartPanel
              title={`Vade eğrisi${curveFor ? ` · ${curveFor}` : ''}`}
              legend="Dikey: uzlaşma fiyatı · Nokta boyu: o vadedeki açık pozisyon. Son fiyat değil uzlaşma — uzak vadeler bir seans işlem görmeyebilir ve son fiyatları farklı anlara ait olur."
            >
              {isLoading ? (
                <div className="shimmer h-[240px]" />
              ) : (
                <ViopTermCurve underlying={curveFor} points={curve} />
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Vadelere dağılım"
              legend="Yükseklik: o vadedeki açık pozisyon · Renk: dayanak kimliği. Açık pozisyon artarken ön vade boşalıyorsa bu yeni risk değil, roll."
            >
              {isLoading ? (
                <div className="shimmer h-[240px]" />
              ) : (
                <ViopExpiryStack stacks={stacks} keys={bands} />
              )}
            </BistChartPanel>
          </div>

          <div className="surface surface-flat flex min-h-0 flex-col overflow-hidden">
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(row, index) => `${row.contract}#${index}`}
              isLoading={isLoading}
              initialSort={{ key: 'oi', direction: 'desc' }}
              emptyMessage="Açık sözleşme bulunamadı."
            />
          </div>
        </>
      )}
    </BistPageShell>
  );
}
