'use client';

import { AlertTriangle, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup from '@/components/ui/ToggleGroup';
import { useBistFund } from '@/hooks/useBist';
import {
  EMPTY,
  formatDate,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  toneClass,
} from '@/lib/bist-format';
import { allocationSegments, formatWeight } from '@/lib/fund-allocation';
import BistChart from './BistChart';
import FundAllocationBar from './FundAllocationBar';
import FundHoldingsCard from './FundHoldingsCard';
import MetricTile from './MetricTile';
import ReturnCell from './ReturnCell';

interface BistFundDetailPageProps {
  code: string;
}

const WINDOWS = [
  { value: '3', label: '3 ay' },
  { value: '6', label: '6 ay' },
  { value: '12', label: '1 yıl' },
  { value: '36', label: '3 yıl' },
  { value: '60', label: '5 yıl' },
] as const;

const PERIOD_LABELS: Record<string, string> = {
  '1a': '1 ay',
  '3a': '3 ay',
  '6a': '6 ay',
  yb: 'Yılbaşı',
  '1y': '1 yıl',
  '3y': '3 yıl',
  '5y': '5 yıl',
};

/**
 * One fund: its net asset value curve and the statistics the screener could not
 * afford to compute for every row.
 *
 * The ratios are the reason this page exists. A six-month return at the top of
 * a league table says nothing about whether its holder could have sat through
 * the drawdown that produced it, and the recovery figure is the one that
 * usually settles the question.
 */
export default function BistFundDetailPage({ code }: BistFundDetailPageProps) {
  const fundCode = code.toUpperCase();
  const [months, setMonths] = useState<(typeof WINDOWS)[number]['value']>('12');
  const { data, isLoading, isError, error } = useBistFund(fundCode, Number(months));

  const headingRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (data) headingRef.current?.focus();
  }, [data]);

  const notFound = isError && (error as { status?: number })?.status === 404;
  const metrics = data?.metrics;

  return (
    <div lang="tr" className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line px-4 py-3">
        <Link
          href="/bist/fonlar"
          className="inline-flex items-center gap-1.5 text-sm text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Fonlar
        </Link>
      </div>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-[1400px] space-y-4">
          {isLoading && !data ? (
            <div className="surface shimmer h-56" />
          ) : isError || !data || !metrics ? (
            <div className="surface">
              <StatusMessage
                icon={AlertTriangle}
                action={
                  <Link
                    href="/bist/fonlar"
                    className="rounded-md border border-line px-3 py-1 text-sm text-fg transition-colors hover:border-line-strong"
                  >
                    Fon listesine dön
                  </Link>
                }
              >
                {notFound ? `${fundCode} TEFAS'ta bulunamadı.` : `${fundCode} verisi alınamadı.`}
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
                  <h1 className="text-xl font-semibold text-fg">{data.code}</h1>
                  <p className="max-w-2xl text-base text-fg-muted">{data.title}</p>
                  <p className="mt-1 text-2xs text-fg-subtle">
                    {data.umbrella}
                    {data.risk_value !== null && ` · Risk ${data.risk_value}/7`}
                    {data.category_rank !== null &&
                      data.category_size !== null &&
                      ` · Kategoride ${data.category_rank}/${data.category_size}`}
                    {!data.tradable && ' · TEFAS’a kapalı'}
                  </p>
                </div>
                <ToggleGroup
                  label="Dönem"
                  options={WINDOWS.map((option) => ({ ...option }))}
                  value={months}
                  onChange={setMonths}
                />
              </header>

              <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
                <MetricTile
                  label="Dönem getirisi"
                  value={formatSignedPercent(metrics.total_return)}
                  tone={toneClass(metrics.total_return)}
                  note={`${metrics.observations} işlem günü`}
                />
                <MetricTile
                  label="Yıllık getiri"
                  value={formatSignedPercent(metrics.annualised_return)}
                  tone={toneClass(metrics.annualised_return)}
                  note="geometrik"
                />
                <MetricTile
                  label="Volatilite"
                  value={formatPercent(metrics.volatility)}
                  note="yıllıklandırılmış"
                />
                <MetricTile
                  label="Sharpe"
                  value={formatNumber(metrics.sharpe, 2)}
                  title={
                    data.risk_free_rate === null
                      ? 'Risksiz faiz bilinmiyor — oran ham getiri/risk olarak hesaplandı'
                      : `Risksiz faiz ${formatPercent(data.risk_free_rate)} üzerinden`
                  }
                  note={
                    data.risk_free_rate === null
                      ? 'risksiz faiz yok'
                      : `rf ${formatPercent(data.risk_free_rate)}`
                  }
                />
                <MetricTile
                  label="Sortino"
                  value={formatNumber(metrics.sortino, 2)}
                  note="yalnızca aşağı yönlü risk"
                />
                <MetricTile
                  label="Maks. düşüş"
                  value={formatPercent(metrics.max_drawdown)}
                  tone={metrics.max_drawdown === null ? undefined : 'text-down'}
                  note={
                    metrics.recovery_days === null
                      ? 'henüz toparlanmadı'
                      : `${metrics.recovery_days} günde toparlandı`
                  }
                />
              </div>

              <div className="surface surface-flat overflow-hidden">
                <div className="flex items-center justify-between border-b border-line px-3 py-2">
                  <h2 className="text-base font-semibold text-fg">Birim pay değeri</h2>
                  <span className="label">Calmar {formatNumber(metrics.calmar, 2)}</span>
                </div>
                <div className="p-2">
                  <BistChart
                    height={300}
                    formatValue={(value) => formatNumber(value, 4)}
                    series={[
                      {
                        name: data.code,
                        color: '--fg',
                        area: true,
                        points: data.series.map((point) => [point.date, point.price]),
                      },
                    ]}
                  />
                </div>
              </div>

              <div className="surface surface-flat overflow-hidden">
                <h2 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">
                  Dönemsel getiri
                </h2>
                <div className="grid grid-cols-2 gap-px bg-line sm:grid-cols-4 lg:grid-cols-7">
                  {Object.keys(PERIOD_LABELS).map((key) => {
                    const framed = data.framed_returns[key];
                    const available = data.real_return.deflatable_windows.includes(key);
                    return (
                      <div key={key} className="bg-surface px-3 py-2">
                        <p className="label">{PERIOD_LABELS[key]}</p>
                        <div className="mt-1 flex justify-start">
                          {framed ? (
                            <ReturnCell framed={framed} realAvailable={available} />
                          ) : (
                            <span className="text-fg-subtle">{EMPTY}</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="surface surface-flat overflow-hidden">
                <div className="flex items-center justify-between border-b border-line px-3 py-2">
                  <h2 className="text-base font-semibold text-fg">Portföy dağılımı</h2>
                  {data.allocation && (
                    <span className="label">{formatDate(data.allocation.as_of)}</span>
                  )}
                </div>
                {data.allocation ? (
                  <div className="space-y-3 p-3">
                    <FundAllocationBar
                      segments={allocationSegments(
                        Object.fromEntries(
                          data.allocation.buckets.map((bucket) => [bucket.key, bucket.weight])
                        ),
                        Object.fromEntries(
                          data.allocation.buckets.map((bucket) => [bucket.key, bucket.label])
                        )
                      )}
                      total={data.allocation.total}
                      height="wide"
                      showLegend
                    />
                    <div className="divide-y divide-line border-t border-line">
                      {data.allocation.buckets.map((bucket) => (
                        <div key={bucket.key} className="py-2">
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="text-sm text-fg">{bucket.label}</span>
                            <span className="tabnum text-sm text-fg">
                              {formatWeight(bucket.weight)}
                            </span>
                          </div>
                          {/* Only when the bucket is more than one line. A
                              single-line bucket *is* its line, and printing
                              both says the same number twice. */}
                          {bucket.lines.length > 1 &&
                            bucket.lines.map((line) => (
                              <div
                                key={line.code}
                                className="flex items-baseline justify-between gap-3 pl-4 pt-1"
                              >
                                <span className="truncate text-2xs text-fg-muted">
                                  {line.label}
                                </span>
                                <span className="tabnum text-2xs text-fg-muted">
                                  {formatWeight(line.weight)}
                                </span>
                              </div>
                            ))}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  /* The card stays rather than disappearing: an absence that is
                     explained is a fact, and a card that is simply not there
                     reads as a page that broke. */
                  <p className="p-3 text-sm text-fg-subtle">
                    TEFAS bu fon için portföy dağılımı yayımlamıyor.
                  </p>
                )}
              </div>

              {/* Under the allocation card on purpose: it answers the question
                  that card raises. "%44 hisse senedi" invites "hangi hisseler",
                  and the two denominators only make sense in that order. */}
              <FundHoldingsCard code={data.code} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
