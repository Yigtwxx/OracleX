'use client';

import { ExternalLink } from 'lucide-react';
import Link from 'next/link';

import { useBistAssetOwners } from '@/hooks/useBist';
import { formatCompactTry, formatDate, formatPercent } from '@/lib/bist-format';
import { formatStakeDelta, holderCoverage, holderHeadline, sinceLabel } from '@/lib/bist-ownership';
import MetricTile from '../MetricTile';
import OwnershipMoves from './OwnershipMoves';
import StakeMovesList from './StakeMovesList';

interface StockOwnersPanelProps {
  ticker: string;
}

/**
 * Who holds this company — the asset-first half of the Ortaklık feature,
 * inlined on the company page rather than opened as a modal, because the
 * company page is where a reader already is when they ask.
 *
 * Three answers the panel must keep apart, and does by status code: the
 * board has not been built (503), the company is outside the XU100 the board
 * covers (404), and nobody crosses the 5% threshold (200 with no rows). Only
 * the last one means what an empty list looks like it means.
 */
export default function StockOwnersPanel({ ticker }: StockOwnersPanelProps) {
  const { data, isLoading, isError, error } = useBistAssetOwners(ticker);
  const status = (error as { status?: number } | null)?.status;

  return (
    <div className="surface surface-flat overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
        <h2 className="text-base font-semibold text-fg">Ortaklık yapısı</h2>
        {data && (
          <span className="flex items-center gap-2 text-2xs text-fg-subtle">
            {data.stale && <span className="text-warn">eski tablo</span>}
            <span>{formatDate(data.as_of)}</span>
            <Link href="/bist/ortaklik" className="text-fg-muted hover:underline">
              Pano →
            </Link>
          </span>
        )}
      </div>

      {isLoading && !data ? (
        <div className="shimmer m-3 h-24" />
      ) : isError || !data ? (
        <p className="px-3 py-4 text-sm text-fg-subtle">
          {status === 404
            ? `${ticker} XU100 dışında; ortaklık tablosu yalnızca XU100 şirketleri için toplanıyor.`
            : status === 503
              ? 'Ortaklık panosu henüz oluşturulmadı. Sunucu açılışında birkaç dakika içinde hazırlanır.'
              : 'Ortaklık verisi alınamadı.'}
        </p>
      ) : (
        <div className="space-y-3 p-3">
          <div className="grid gap-2 sm:grid-cols-3">
            <MetricTile
              label="Yabancı oranı"
              value={formatPercent(data.foreign_ratio_pct)}
              title="Yabancı yatırımcıların halka açık kısımdaki payı (Takasbank saklama)"
            />
            <MetricTile
              label="Halka açıklık"
              value={formatPercent(data.free_float_pct)}
              title="Fiilen işlem görebilen pay oranı"
            />
            <MetricTile
              label="Adı geçen ortaklar"
              value={formatPercent(holderCoverage(data).namedPct)}
              note={`${data.holders.length} ortak · ${holderCoverage(data).tracked} takipte`}
              title="%5 eşiğini geçen ortakların toplam payı"
            />
          </div>

          <p className="text-sm text-fg-muted">{holderHeadline(data)}</p>

          {data.holders.length > 0 && (
            <ul className="divide-y divide-line rounded-md border border-line">
              {data.holders.map((holder) => (
                <li
                  key={holder.label}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate">
                    {holder.tracked && holder.entity_id ? (
                      <Link
                        href={`/bist/ortaklik?entity=${encodeURIComponent(holder.entity_id)}`}
                        className="text-fg hover:underline"
                      >
                        {holder.label}
                      </Link>
                    ) : (
                      <span className="text-fg">{holder.label}</span>
                    )}
                    {!holder.tracked && (
                      <span
                        className="ml-1.5 rounded border border-line px-1 py-px text-2xs text-fg-subtle"
                        title="Bu ortak panoda bir kart olarak izlenmiyor; tablo yine de tam."
                      >
                        takip dışı
                      </span>
                    )}
                  </span>
                  <span className="tabnum shrink-0 text-right">
                    <span className="text-fg">{formatPercent(holder.stake_pct)}</span>
                    {holder.delta_pct !== null && Math.abs(holder.delta_pct) >= 0.0001 && (
                      <span
                        className={`ml-2 text-2xs ${holder.delta_pct > 0 ? 'text-up' : 'text-down'}`}
                        title="Bir önceki günlük kayda göre"
                      >
                        {formatStakeDelta(holder.delta_pct)}
                      </span>
                    )}
                    <span className="ml-2 text-2xs text-fg-subtle">
                      {holder.value_try === null ? '' : formatCompactTry(holder.value_try)}
                    </span>
                    <span
                      className="ml-2 text-2xs text-fg-subtle"
                      title="Pay tablosunda ilk görüldüğü gün; ≤ ise kayıt başlangıcında zaten vardı"
                    >
                      {sinceLabel(holder.since, holder.at_baseline)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          {data.funds.length > 0 && (
            <div>
              <p className="label mb-1">Bu hisseyi tutan izlenen fonlar</p>
              <ul className="divide-y divide-line rounded-md border border-line">
                {data.funds.map((fund) => (
                  <li
                    key={fund.entity_id}
                    className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 truncate">
                      <Link
                        href={`/bist/ortaklik?entity=${encodeURIComponent(fund.entity_id)}`}
                        className="text-fg hover:underline"
                      >
                        {fund.name}
                      </Link>
                      <span className="ml-1.5 text-2xs text-fg-subtle">
                        {fund.code}
                        {fund.as_of ? ` · ${fund.as_of}` : ''}
                      </span>
                    </span>
                    <span className="tabnum shrink-0 text-right text-fg-muted">
                      <span title="Fonun hisse kitabındaki ağırlığı">
                        {formatPercent(fund.weight_in_fund_pct)} fonda
                      </span>
                      <span
                        className="ml-2 text-2xs text-fg-subtle"
                        title="Şirket sermayesindeki pay"
                      >
                        {formatPercent(fund.stake_pct, 2)} sermaye
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <p className="label mb-1">
              Pay giriş ve çıkışları
              {data.tracking_since && (
                <span className="ml-2 normal-case tracking-normal text-fg-subtle">
                  kayıt {formatDate(data.tracking_since)} tarihinden beri
                </span>
              )}
            </p>
            <div className="rounded-md border border-line">
              <StakeMovesList
                moves={data.stake_moves}
                trackingSince={data.tracking_since}
                showCompany={false}
                limit={8}
              />
            </div>
          </div>

          <div>
            <p className="label mb-1">Ortaklık bildirimleri</p>
            <div className="rounded-md border border-line">
              <OwnershipMoves
                moves={data.moves}
                limit={6}
                empty="Tapede bu şirket için içeriden işlem, pay devri veya sermaye bildirimi yok."
              />
            </div>
          </div>

          {data.source_url && (
            <p className="text-2xs text-fg-subtle">
              Kaynak:{' '}
              <a
                href={data.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 text-fg-muted hover:underline"
              >
                İş Yatırım şirket kartı
                <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
              </a>{' '}
              · %5 üzeri ortaklar; değerler güncel piyasa değeriyle çarpılarak hesaplanmıştır.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
