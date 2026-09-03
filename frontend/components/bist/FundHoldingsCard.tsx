'use client';

import { ExternalLink } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

import { useBistFundHoldings } from '@/hooks/useBist';
import type { BistFundHoldingsReason } from '@/lib/bist-api';
import { formatCompactTry, formatPercent } from '@/lib/bist-format';

interface FundHoldingsCardProps {
  code: string;
  fundType?: string;
}

const MONTHS = [
  'Ocak',
  'Şubat',
  'Mart',
  'Nisan',
  'Mayıs',
  'Haziran',
  'Temmuz',
  'Ağustos',
  'Eylül',
  'Ekim',
  'Kasım',
  'Aralık',
];

/**
 * Why the card is empty, in the reader's terms.
 *
 * Four sentences rather than one, because only the second of them means the
 * fund owns no stocks. A single "no data" would say that about all four.
 */
const REASONS: Record<BistFundHoldingsReason, string> = {
  no_report:
    'Bu fon için KAP’ta portföy dağılım raporu yok. Raporlar her ayı takip eden ilk günlerde yayımlanır.',
  no_equity: 'Fonun son raporunda hisse senedi pozisyonu yok.',
  unreadable:
    'Fonun son raporu, kurucusunun kullandığı tabloyu okuyamadığımız bir biçimde yayımlanmış.',
  not_listed: 'Fon KAP’ın aktif fon listesinde yer almıyor.',
  unavailable: 'KAP’a şu anda ulaşılamıyor.',
};

/** Shown before the list is expanded. Enough to answer "what does it hold". */
const PREVIEW = 10;

/**
 * The companies the fund actually owns.
 *
 * The one thing on this page that does not come from TEFAS. TEFAS says how much
 * of a fund is equity; this says which equities, and it costs a monthly KAP
 * filing to know — so the figures are a month or more behind the rest of the
 * page and the card says so rather than sitting next to daily numbers pretending
 * otherwise.
 *
 * **The weights are shares of the fund's equity book, not of the fund.** The
 * two layouts KAP filings come in do not agree on the second denominator, and
 * one of them cannot be converted to it without inventing a number. The
 * allocation card above already gives the fund-level equity share, so the two
 * are shown apart rather than multiplied together.
 */
export default function FundHoldingsCard({ code, fundType = 'YAT' }: FundHoldingsCardProps) {
  const { data, isLoading } = useBistFundHoldings(code, fundType);
  const [expanded, setExpanded] = useState(false);

  const holdings = data?.holdings ?? [];
  // The bars are scaled to the largest position, not to 100%. A book whose top
  // holding is 11% would otherwise draw eleven near-invisible slivers and say
  // nothing about the shape of the list, which is the only thing a bar adds
  // here — the exact figure is printed beside it either way.
  const largest = holdings.length > 0 ? holdings[0].weight : 1;
  const shown = expanded ? holdings : holdings.slice(0, PREVIEW);
  const asOf = data?.as_of;
  const period = asOf ? `${MONTHS[Math.min(Math.max(asOf.period, 1), 12) - 1]} ${asOf.year}` : null;

  return (
    <div className="surface surface-flat overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="text-base font-semibold text-fg">Fonun hisse portföyü</h2>
        <div className="flex items-center gap-3">
          {period && <span className="label">{period}</span>}
          {data?.source_url && (
            <a
              href={data.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-2xs text-fg-muted transition-colors hover:text-fg"
            >
              KAP bildirimi
              <ExternalLink className="h-3 w-3" aria-hidden="true" />
            </a>
          )}
        </div>
      </div>

      {isLoading && !data ? (
        <div className="shimmer h-28" />
      ) : holdings.length === 0 ? (
        <p className="p-3 text-sm text-fg-subtle">
          {data?.reason ? REASONS[data.reason] : REASONS.unavailable}
        </p>
      ) : (
        <>
          <div className="divide-y divide-line">
            {shown.map((holding) => (
              <div key={holding.ticker} className="flex items-center gap-3 px-3 py-2">
                <Link
                  href={`/bist/hisseler/${holding.ticker}`}
                  className="w-[72px] shrink-0 font-medium text-fg transition-colors hover:text-accent"
                >
                  {holding.ticker}
                </Link>
                <span className="min-w-0 flex-1 truncate text-2xs text-fg-muted">
                  {holding.label}
                </span>
                {/* A bar rather than only a number: the list is read for its
                    shape — one position at forty per cent is the fact, and a
                    column of percentages hides it. */}
                <span
                  className="hidden h-1.5 w-24 shrink-0 overflow-hidden rounded-sm bg-surface-2 sm:block"
                  aria-hidden
                >
                  <span
                    className="block h-full rounded-sm bg-chart-1"
                    style={{
                      width: `${Math.min((holding.weight / largest) * 100, 100)}%`,
                      minWidth: '2px',
                    }}
                  />
                </span>
                <span className="tabnum w-14 shrink-0 text-right text-sm text-fg">
                  {formatPercent(holding.weight)}
                </span>
                <span className="tabnum hidden w-24 shrink-0 text-right text-2xs text-fg-subtle md:block">
                  {formatCompactTry(holding.value)}
                </span>
              </div>
            ))}
          </div>

          {holdings.length > PREVIEW && (
            <button
              type="button"
              onClick={() => setExpanded((open) => !open)}
              className="w-full border-t border-line px-3 py-2 text-2xs text-fg-muted transition-colors hover:text-fg"
            >
              {expanded ? 'Daha az göster' : `${holdings.length - PREVIEW} pozisyon daha göster`}
            </button>
          )}

          <div className="space-y-1 border-t border-line px-3 py-2 text-2xs text-fg-subtle">
            {/* Said plainly, because it is the one thing about this card a
                reader could otherwise get wrong: these add up to the fund's
                stocks, not to the fund. */}
            <p>
              Ağırlıklar fonun hisse senedi portföyüne göre — fonun tamamına göre değil. Fonun ne
              kadarının hisse olduğu yukarıdaki dağılım kartında.
            </p>
            <p>
              Kaynak: KAP aylık portföy dağılım raporu{period ? `, ${period} dönemi` : ''}
              {asOf?.late && ' (geç bildirim)'}. Bu sayfadaki diğer veriler günlük; bu kart aylık.
              {data?.stale && ' Şu an önceki çekimden geliyor.'}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
