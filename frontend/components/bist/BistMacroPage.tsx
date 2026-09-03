'use client';

import { AlertTriangle, ExternalLink, RefreshCw, ShieldAlert } from 'lucide-react';
import { useMemo } from 'react';

import StatusMessage from '@/components/ui/StatusMessage';
import { useBistMacro, useBistMacroNote, useBistRestrictions } from '@/hooks/useBist';
import {
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
  toneClass,
} from '@/lib/bist-format';
import BistChart from './BistChart';
import BistMacroNote from './BistMacroNote';
import BistPageShell from './BistPageShell';
import MetricTile from './MetricTile';

/**
 * The macro backdrop, and the measuring stick every return on this realm is
 * held against.
 *
 * The real policy rate is computed server-side with the Fisher relation rather
 * than by subtraction, and it is the one figure here a reader is most likely to
 * work out wrong in their head: at 37% against 32%, subtracting gives 5 points
 * and the true answer is under 4.
 *
 * The restriction radar shares this page because a trading measure is a rule
 * imposed from outside a company — the same class of fact as a policy rate,
 * and a different class from company news.
 */
export default function BistMacroPage() {
  const { data, isLoading, isError, isFetching, refetch } = useBistMacro('5y');
  const restrictions = useBistRestrictions(20);
  const note = useBistMacroNote();

  const showColdError = isError && !data;

  // The lira against the dollar, over five years. The single most requested
  // chart on any Turkish finance page, and the reason `usd` is a column
  // everywhere else in this realm.
  const fxSeries = useMemo(
    () =>
      data
        ? [
            {
              name: 'USD/TRY',
              color: '--down',
              area: true,
              points: data.usdtry_series.map(
                (point) => [point.date, point.rate] as [string, number]
              ),
            },
          ]
        : [],
    [data]
  );

  const cpiSeries = useMemo(
    () =>
      data && data.cpi_series.length > 0
        ? [
            {
              name: 'TÜFE',
              color: '--warn',
              area: true,
              points: data.cpi_series.map(
                (point) => [point.month, point.index] as [string, number]
              ),
            },
          ]
        : [],
    [data]
  );

  return (
    <BistPageShell
      title="Makro"
      description="TCMB faizi, enflasyon, kur ve tedbir radarı."
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
            Makro serileri alınamadı.
          </StatusMessage>
        </div>
      ) : isLoading && !data ? (
        <div className="surface shimmer h-40" />
      ) : data ? (
        <>
          <BistMacroNote data={note.data} isLoading={note.isLoading} />

          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <MetricTile
              label="Enflasyon"
              value={formatPercent(data.inflation_yoy)}
              note="yıllık TÜFE"
            />
            <MetricTile label="ÜFE" value={formatPercent(data.ppi_yoy)} note="yıllık" />
            <MetricTile
              label="Politika faizi"
              value={formatPercent(data.policy_rate)}
              note="TCMB"
            />
            <MetricTile
              label="Reel faiz"
              value={formatPercent(data.real_policy_rate)}
              tone={toneClass(data.real_policy_rate)}
              title="Fisher ilişkisiyle: (1+faiz)/(1+enflasyon)−1. Çıkarma işlemi bu seviyelerde yanlış sonuç verir."
              note="enflasyona göre"
            />
            <MetricTile label="USD/TRY" value={formatNumber(data.usdtry, 4)} />
            <MetricTile label="EUR/TRY" value={formatNumber(data.eurtry, 4)} />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="surface surface-flat overflow-hidden">
              <h2 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">
                Dolar kuru · 5 yıl
              </h2>
              <div className="p-2">
                <BistChart
                  height={240}
                  series={fxSeries}
                  formatValue={(value) => formatNumber(value, 2)}
                />
              </div>
            </div>

            <div className="surface surface-flat overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-3 py-2">
                <h2 className="text-base font-semibold text-fg">TÜFE endeksi</h2>
                {!data.cpi_source && <span className="label">EVDS anahtarı yok</span>}
              </div>
              <div className="p-2">
                {cpiSeries.length > 0 ? (
                  <BistChart
                    height={240}
                    series={cpiSeries}
                    formatValue={(value) => formatNumber(value, 1)}
                  />
                ) : (
                  <div className="flex h-[240px] flex-col items-center justify-center gap-2 px-6 text-center">
                    <p className="text-sm text-fg-muted">
                      TÜFE serisi TCMB’nin EVDS servisinden geliyor ve bir API anahtarı istiyor.
                    </p>
                    <p className="text-2xs text-fg-subtle">
                      Anahtar olmadan 1 yıllık reel getiri yine hesaplanıyor — yayımlanan yıllık
                      enflasyon o pencerenin tam deflatörü. Daha uzun dönemler nominal kalıyor.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="surface surface-flat overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-3 py-2">
              <h2 className="flex items-center gap-2 text-base font-semibold text-fg">
                <ShieldAlert className="h-3.5 w-3.5 text-warn" aria-hidden="true" />
                Tedbir radarı
              </h2>
              <span className="label">Borsa İstanbul duyuruları · KAP</span>
            </div>
            {restrictions.isError ? (
              <p className="px-3 py-4 text-sm text-fg-subtle">
                Tedbir listesi alınamadı — KAP akışı şu anda yanıt vermiyor.
              </p>
            ) : (restrictions.data?.restrictions.length ?? 0) === 0 ? (
              <p className="px-3 py-4 text-sm text-fg-subtle">
                Yakın tarihte açığa satış yasağı, brüt takas veya devre kesici duyurusu bulunamadı.
              </p>
            ) : (
              <ul>
                {restrictions.data?.restrictions.map((item) => (
                  <li key={item.index} className="border-b border-line last:border-0">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-start gap-3 px-3 py-2 transition-colors hover:bg-surface-2"
                    >
                      <span className="w-16 shrink-0 text-sm font-medium text-fg">
                        {item.ticker || '—'}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-fg">{item.title}</span>
                        <span className="block truncate text-2xs text-fg-subtle">
                          {item.summary || item.company}
                        </span>
                      </span>
                      <span
                        className="shrink-0 text-2xs text-fg-subtle"
                        title={formatDateTime(item.published_at)}
                      >
                        {formatRelative(item.published_at)}
                      </span>
                      <ExternalLink
                        className="mt-0.5 h-3 w-3 shrink-0 text-fg-subtle"
                        aria-hidden="true"
                      />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <p className="text-2xs text-fg-subtle">
            Kaynak: TCMB politika faizi ve TÜFE, TÜİK enflasyon serisi, Yahoo Finance kur serisi.
            Son okuma {formatDateTime(data.as_of)}.
          </p>
        </>
      ) : null}
    </BistPageShell>
  );
}
