'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';
import Link from 'next/link';

import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import { useBistOverview } from '@/hooks/useBist';
import type { BistStock } from '@/lib/bist-api';
import {
  CAPITAL_ACTION_NOTE,
  EMPTY,
  SESSION_LABEL,
  formatCompactTry,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  isLikelyCapitalAction,
  sessionState,
  toneClass,
} from '@/lib/bist-format';
import BistBrief from './BistBrief';
import BistRibbon from './BistRibbon';
import OverviewCalendar from './OverviewCalendar';
import BistPageShell from './BistPageShell';
import MetricTile from './MetricTile';
import SectorHeatmap from './SectorHeatmap';

/**
 * The two indices the rail carries, in the order a reader checks them.
 *
 * Stated here rather than taken from the payload, which arrives in the
 * exchange's own ordering. The other six the API returns are slices of the same
 * number and used to open this page as eight tiles; they are one click away on
 * the screener, which is where a reader who wants XU050 is already going.
 */
const HEADLINE_INDICES = ['XU100', 'XU030'];

/**
 * One company on a list, as a row.
 *
 * Split out of `MoverList` because two different panels draw it now, and the
 * capital-action guard is the reason it must not be duplicated: a move past the
 * daily price limit did not happen through trading, and a reader scanning a
 * losers column takes an unadjusted bonus issue for a collapse. The board has
 * had `isLikelyCapitalAction` since the screener needed it; this is the surface
 * where being wrong about it is most expensive.
 */
function MoverRow({
  row,
  value,
  tone,
}: {
  row: BistStock;
  value: string;
  /** Colour for the figure. Turnover is not a direction, so it stays neutral. */
  tone?: string;
}) {
  const suspect = isLikelyCapitalAction(row.change_pct);
  return (
    <li>
      <Link
        href={`/bist/hisseler/${row.ticker}`}
        className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5 text-sm transition-colors hover:bg-surface-2"
      >
        <span className="min-w-0">
          <span className="font-medium text-fg">{row.ticker}</span>
          <span className="ml-2 truncate text-2xs text-fg-subtle">{row.sector}</span>
        </span>
        <span className="flex shrink-0 items-baseline gap-1">
          {suspect && (
            <span
              className="text-2xs text-warn"
              title={CAPITAL_ACTION_NOTE}
              aria-label={CAPITAL_ACTION_NOTE}
            >
              ⚠
            </span>
          )}
          <span className={`tabnum ${tone ?? toneClass(row.change_pct)}`}>{value}</span>
        </span>
      </Link>
    </li>
  );
}

/**
 * Both ends of the session in one panel.
 *
 * Five each rather than ten each. Two ten-row columns spent a third of the
 * board on the same question asked twice, and the answer a reader wants from
 * this panel — which way today went and by how much — is legible in five rows
 * per side. Five also fills the band beside a ten-row list, which three did
 * not. The rule between them is what makes it one reading instead of two lists
 * that happen to be adjacent.
 */
function MoversPanel({ gainers, losers }: { gainers: BistStock[]; losers: BistStock[] }) {
  const top = gainers.slice(0, 5);
  const bottom = losers.slice(0, 5);

  return (
    <div className="surface surface-flat flex flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 className="text-base font-semibold text-fg">Yükselen ve düşenler</h3>
        <Link href="/bist/hisseler" className="label transition-colors hover:text-fg">
          Tümü
        </Link>
      </div>

      <ul className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
        {top.length === 0 && bottom.length === 0 && (
          <li className="px-3 py-4 text-sm text-fg-subtle">{EMPTY}</li>
        )}
        {top.map((row) => (
          <MoverRow key={row.ticker} row={row} value={formatSignedPercent(row.change_pct)} />
        ))}
        {top.length > 0 && bottom.length > 0 && (
          // A heavier rule than the row borders: this is the turn of the
          // session, not the next row down.
          <li aria-hidden="true" className="border-b-2 border-line-strong" />
        )}
        {bottom.map((row) => (
          <MoverRow key={row.ticker} row={row} value={formatSignedPercent(row.change_pct)} />
        ))}
      </ul>

      {/* Why the top and bottom rows so often read exactly ±%10,0. Without it
          the panel looks like it is rounding, and a reader who does not know
          Borsa İstanbul caps a session's move has no way to tell the two
          apart. */}
      <p className="shrink-0 border-t border-line px-3 py-1.5 text-2xs text-fg-subtle">
        Günlük fiyat limiti ±%10 · limitin dışındaki hareketler ⚠ ile işaretlenir
      </p>
    </div>
  );
}

/**
 * A short list of companies — gainers, losers, most traded.
 *
 * `tone` is separate from `valueOf` because the two are not always the same
 * quantity: the most-traded list shows turnover, and painting a volume red
 * because the price fell invites it to be read as a negative volume.
 */
function MoverList({
  title,
  rows,
  valueOf,
  tone,
}: {
  title: string;
  rows: BistStock[];
  valueOf: (row: BistStock) => string;
  tone?: (row: BistStock) => string;
}) {
  return (
    <div className="surface surface-flat flex flex-col overflow-hidden">
      <h3 className="shrink-0 border-b border-line px-3 py-2 text-base font-semibold text-fg">
        {title}
      </h3>
      <ul className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 && <li className="px-3 py-4 text-sm text-fg-subtle">{EMPTY}</li>}
        {rows.map((row) => (
          <MoverRow key={row.ticker} row={row} value={valueOf(row)} tone={tone?.(row)} />
        ))}
      </ul>
    </div>
  );
}

/**
 * The BIST realm's landing board.
 *
 * Answers, in order: where the index is, how broad the move is, which sectors
 * carried it, and which names moved most. The macro strip sits at the bottom
 * rather than the top because it is the context for the day rather than the
 * day itself.
 */
export default function BistOverviewPage() {
  const { data, isLoading, isError, refetch, isFetching } = useBistOverview();

  // A failed *refresh* must never blank a populated board — only a cold
  // failure gets the whole pane.
  const showColdError = isError && !data;
  const session = sessionState();

  const headline = HEADLINE_INDICES.map((code) =>
    data?.indices.find((index) => index.code === code)
  ).filter((index): index is NonNullable<typeof index> => !!index);

  return (
    <BistPageShell
      title="Genel Bakış"
      description="XU100, sektör dağılımı ve günün öne çıkanları."
      delayed
      ribbon={
        data ? <BistRibbon sentiment={data.sentiment} dominance={data.dominance} /> : undefined
      }
      action={
        <span className="flex items-center gap-2">
          <span className="label">{SESSION_LABEL[session]}</span>
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Yenile"
            className="rounded-md p-1 text-fg-subtle transition-colors hover:text-fg"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
        </span>
      }
    >
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
            Borsa İstanbul verisi şu anda alınamıyor.
          </StatusMessage>
        </div>
      ) : isLoading && !data ? (
        <div className="surface">
          <StatusMessage icon={RefreshCw}>Board yükleniyor…</StatusMessage>
        </div>
      ) : data ? (
        <>
          <StaleStrip
            stale={data.stale}
            refreshFailed={isError}
            asOf={data.as_of}
            onRetry={() => refetch()}
          />

          {/* What the reader follows, not what the exchange publishes. The
              eight index tiles that used to open this page were seven slices of
              one number; XU100 and XU030 kept their place in the market rail on
              the right, where the day's other context already sits. */}
          <BistBrief />

          <div className="grid gap-3 lg:grid-cols-[2fr_1fr]">
            <div className="surface surface-flat overflow-hidden">
              <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
                <h3 className="text-base font-semibold text-fg">Sektörler</h3>
                <span className="label">Piyasa değeri ağırlıklı</span>
              </div>
              <div className="p-2">
                <SectorHeatmap sectors={data.sectors} />
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <div className="surface surface-flat p-3">
                <p className="label">Piyasa genişliği</p>
                <div className="mt-2 flex items-end gap-3">
                  <span className="tabnum text-2xl font-semibold text-up">
                    {data.breadth.advancers}
                  </span>
                  <span className="text-fg-subtle">▲ / ▼</span>
                  <span className="tabnum text-2xl font-semibold text-down">
                    {data.breadth.decliners}
                  </span>
                </div>
                <p className="mt-1 text-2xs text-fg-subtle">
                  {data.breadth.unchanged} değişmedi · {data.breadth.total} hisse
                </p>
                {/* A single bar is enough: the question is which side is
                    heavier, not by exactly how many. */}
                <div className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <span
                    className="bg-up"
                    style={{
                      width: `${(data.breadth.advancers / Math.max(1, data.breadth.total)) * 100}%`,
                    }}
                  />
                  <span
                    className="bg-down"
                    style={{
                      width: `${(data.breadth.decliners / Math.max(1, data.breadth.total)) * 100}%`,
                    }}
                  />
                </div>
              </div>

              {data.macro && (
                <div className="grid grid-cols-2 gap-2">
                  <MetricTile
                    label="Enflasyon"
                    value={formatPercent(data.macro.inflation_yoy)}
                    note="yıllık TÜFE"
                  />
                  <MetricTile
                    label="Politika faizi"
                    value={formatPercent(data.macro.policy_rate)}
                    note={
                      data.macro.real_policy_rate === null
                        ? 'reel: —'
                        : `reel ${formatSignedPercent(data.macro.real_policy_rate)}`
                    }
                    tone={toneClass(data.macro.real_policy_rate)}
                  />
                  <MetricTile label="USD/TRY" value={formatNumber(data.macro.usdtry, 4)} />
                  <MetricTile label="EUR/TRY" value={formatNumber(data.macro.eurtry, 4)} />
                </div>
              )}

              {/* The two indices a reader actually checks, in the rail rather
                  than across the top. Outside the `macro` guard because an
                  index is published whether or not the macro series resolved. */}
              {headline.length > 0 && (
                <div className="grid grid-cols-2 gap-2">
                  {headline.map((index) => (
                    <MetricTile
                      key={index.code}
                      label={index.code}
                      value={formatNumber(index.value, 2)}
                      tone={toneClass(index.change_pct)}
                      title={index.name}
                      note={
                        <>
                          {formatSignedPercent(index.change_pct)} · yılbaşı{' '}
                          {formatSignedPercent(index.perf_ytd)}
                        </>
                      }
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* One band, three panels, each scrolling what does not fit.
              Sized to the two ten-row lists rather than to the calendar, which
              runs to seventy events over three months: a band sized to that
              would leave the other two panels mostly empty, and empty reads as
              missing data rather than as a short list. Sized this way all three
              are full and the calendar scrolls. */}
          <div className="grid gap-3 lg:h-[378px] lg:grid-cols-3">
            <MoversPanel gainers={data.gainers} losers={data.losers} />
            {/* Turnover, not direction — so it stays neutral. Painting a volume
                red because the price fell invites it to be read as a negative
                volume. */}
            <MoverList
              title="En çok işlem görenler"
              rows={data.most_traded}
              valueOf={(row) => formatCompactTry(row.traded_value)}
              tone={() => 'text-fg'}
            />
            <OverviewCalendar />
          </div>

          <p className="text-2xs text-fg-subtle">
            Fiyatlar Borsa İstanbul kaynaklıdır ve en az {data.delay_minutes} dakika gecikmelidir.
            Son güncelleme: <span className="tabnum">{formatDateTime(data.as_of)}</span>
          </p>
        </>
      ) : null}
    </BistPageShell>
  );
}
