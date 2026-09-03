'use client';

import { AlertTriangle, ArrowLeft, ExternalLink } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useRef } from 'react';

import StatusMessage from '@/components/ui/StatusMessage';
import { useBistKap, useBistStock } from '@/hooks/useBist';
import {
  CAPITAL_ACTION_NOTE,
  formatCompactTry,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  formatTry,
  isLikelyCapitalAction,
  toneClass,
} from '@/lib/bist-format';
import BistChart from './BistChart';
import MetricTile from './MetricTile';
import ReturnCell from './ReturnCell';
import StockOwnersPanel from './ownership/StockOwnersPanel';

interface BistStockDetailPageProps {
  ticker: string;
}

/**
 * One company.
 *
 * Follows the community post-detail pattern rather than the asset modal: this
 * is a real route, so back is a `<Link>` and not `router.back()` — a reader who
 * arrived from a bookmark has no history to go back through.
 */
export default function BistStockDetailPage({ ticker }: BistStockDetailPageProps) {
  const code = ticker.toUpperCase();
  const { data, isLoading, isError, error } = useBistStock(code, '1y');
  // The company's own filings. A separate query so a KAP outage costs the tape
  // and not the quote.
  const { data: kap } = useBistKap({ ticker: code, limit: 8 }, !!data);

  const headingRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (data) headingRef.current?.focus();
  }, [data]);

  const notFound = isError && (error as { status?: number })?.status === 404;

  return (
    <div lang="tr" className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line px-4 py-3">
        <Link
          href="/bist/hisseler"
          className="inline-flex items-center gap-1.5 text-sm text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Hisseler
        </Link>
      </div>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-[1400px] space-y-4">
          {isLoading && !data ? (
            <div className="surface shimmer h-56" />
          ) : isError || !data ? (
            <div className="surface">
              <StatusMessage
                icon={AlertTriangle}
                action={
                  <Link
                    href="/bist/hisseler"
                    className="rounded-md border border-line px-3 py-1 text-sm text-fg transition-colors hover:border-line-strong"
                  >
                    Hisse listesine dön
                  </Link>
                }
              >
                {notFound
                  ? `${code} Borsa İstanbul'da işlem görmüyor.`
                  : `${code} verisi alınamadı.`}
              </StatusMessage>
            </div>
          ) : (
            <>
              <header className="flex flex-wrap items-end justify-between gap-4">
                {/* The focus target is the wrapper rather than the heading —
                    matching components/community/PostDetailPage.tsx, so a
                    reader arriving from a permalink lands on the content in
                    exactly one way across the app. */}
                <div ref={headingRef} tabIndex={-1} className="min-w-0 outline-none">
                  <h1 className="text-xl font-semibold text-fg">{data.ticker}</h1>
                  <p className="truncate text-base text-fg-muted">{data.name}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {data.indices.slice(0, 6).map((index) => (
                      <span
                        key={index}
                        className="rounded border border-line px-1.5 py-0.5 text-2xs text-fg-subtle"
                      >
                        {index}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="text-right">
                  <p className="tabnum text-2xl font-semibold text-fg">{formatTry(data.price)}</p>
                  <p
                    className={`tabnum flex items-center justify-end gap-1 text-base ${toneClass(data.change_pct)}`}
                  >
                    {formatSignedPercent(data.change_pct)}
                    {isLikelyCapitalAction(data.change_pct) && (
                      <span title={CAPITAL_ACTION_NOTE} className="text-warn">
                        ⚑
                      </span>
                    )}
                  </p>
                  <p className="text-2xs text-fg-subtle">
                    {data.delay_minutes} dk gecikmeli · {data.sector}
                  </p>
                </div>
              </header>

              <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <MetricTile label="Piyasa değeri" value={formatCompactTry(data.market_cap)} />
                <MetricTile label="F/K" value={formatNumber(data.pe, 1)} title="Fiyat / Kazanç" />
                <MetricTile
                  label="PD/DD"
                  value={formatNumber(data.pb, 2)}
                  title="Piyasa değeri / Defter değeri"
                />
                <MetricTile
                  label="FD/FAVÖK"
                  value={formatNumber(data.ev_ebitda, 1)}
                  title="Firma değeri / FAVÖK"
                />
                <MetricTile
                  label="Halka açıklık"
                  value={formatPercent(data.free_float_pct)}
                  title="Fiilen işlem görebilen pay oranı"
                />
                <MetricTile
                  label="1 yıl getiri"
                  value={<ReturnCell framed={data.returns['1y']} showUsd />}
                />
              </div>

              <div className="surface surface-flat overflow-hidden">
                <div className="flex items-center justify-between border-b border-line px-3 py-2">
                  <h2 className="text-base font-semibold text-fg">Fiyat</h2>
                  <span className="label">
                    52h {formatTry(data.week52_low)} – {formatTry(data.week52_high)}
                  </span>
                </div>
                <div className="p-2">
                  <BistChart
                    height={280}
                    formatValue={(value) => formatNumber(value, 2)}
                    series={[
                      {
                        name: data.ticker,
                        color: '--fg',
                        area: true,
                        points: data.candles.map((candle) => [candle.date, candle.close]),
                      },
                    ]}
                  />
                </div>
              </div>

              <StockOwnersPanel ticker={data.ticker} />

              <div className="surface surface-flat overflow-hidden">
                <h2 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">
                  KAP bildirimleri
                </h2>
                <ul>
                  {(kap?.disclosures ?? []).length === 0 && (
                    <li className="px-3 py-4 text-sm text-fg-subtle">
                      Bu şirket için yakın tarihli bildirim bulunamadı.
                    </li>
                  )}
                  {(kap?.disclosures ?? []).map((item) => (
                    <li key={item.index} className="border-b border-line last:border-0">
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-start justify-between gap-3 px-3 py-2 transition-colors hover:bg-surface-2"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm text-fg">{item.title}</span>
                          <span className="block truncate text-2xs text-fg-subtle">
                            {item.category_label} · {formatDateTime(item.published_at)}
                          </span>
                        </span>
                        <ExternalLink
                          className="mt-0.5 h-3 w-3 shrink-0 text-fg-subtle"
                          aria-hidden="true"
                        />
                      </a>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="text-2xs text-fg-subtle">
                RSI {formatNumber(data.rsi, 1)} · Beta {formatNumber(data.beta, 2)} · Nispi hacim{' '}
                {formatNumber(data.relative_volume, 2)} · Günlük hacim{' '}
                {formatCompactTry(data.traded_value)} · Yılbaşından{' '}
                {formatSignedPercent(data.perf_ytd)}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
