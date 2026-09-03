'use client';

import { AlertTriangle, ExternalLink } from 'lucide-react';

import StatusMessage from '@/components/ui/StatusMessage';
import { useBistOwnershipEntity } from '@/hooks/useBist';
import { formatCompactTry, formatDate } from '@/lib/bist-format';
import { CATEGORY_LABEL } from '@/lib/bist-ownership';
import OwnerAllocationBar from './OwnerAllocationBar';
import OwnerPositionTable from './OwnerPositionTable';
import OwnershipMoves from './OwnershipMoves';
import StakeMovesList from './StakeMovesList';

interface OwnerDetailProps {
  entityId: string;
}

/**
 * One holder in full: header, allocation, every stake, the filings on those
 * companies, and where each figure came from.
 *
 * The coverage note sits under the bar on purpose. A bar that fills to 100%
 * reads as "everything they own", and for every holder here it is only what
 * the XU100 shareholder tables and one fund filing can see.
 */
export default function OwnerDetail({ entityId }: OwnerDetailProps) {
  const { data, isLoading, isError, error } = useBistOwnershipEntity(entityId);
  const notFound = isError && (error as { status?: number })?.status === 404;

  if (isLoading && !data) {
    return <div className="surface shimmer h-72" />;
  }
  if (isError || !data) {
    return (
      <div className="surface">
        <StatusMessage icon={AlertTriangle}>
          {notFound ? 'Bu ortak panoda kayıtlı değil.' : 'Ortak verisi alınamadı.'}
        </StatusMessage>
      </div>
    );
  }

  const {
    entity,
    positions,
    moves,
    stake_moves: stakeMoves,
    sources,
    tracking_since: trackingSince,
  } = data;

  return (
    <div className="space-y-4">
      <header className="surface surface-flat p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-fg">{entity.name}</h2>
            <p className="text-sm text-fg-muted">
              {CATEGORY_LABEL[entity.category]}
              {entity.subtitle ? ` · ${entity.subtitle}` : ''}
            </p>
          </div>
          <div className="text-right">
            <p className="tabnum text-2xl font-semibold text-fg">
              {entity.total_value_try === null ? '—' : formatCompactTry(entity.total_value_try)}
            </p>
            <p className="text-2xs text-fg-subtle">
              {entity.positions_count} pozisyon · {formatDate(entity.as_of)}
              {entity.stale && <span className="ml-1 text-warn">· pano eski</span>}
            </p>
          </div>
        </div>

        <OwnerAllocationBar slices={entity.allocation} height="wide" showLegend className="mt-4" />

        <p className="mt-3 text-2xs text-fg-subtle">
          {entity.coverage_note ??
            'Yalnızca XU100 şirketlerinin %5 üzeri pay tablolarında görünen ve fon raporunda adı geçen pozisyonlar. Toplam, değerlenebilen pozisyonların toplamıdır; bir servet ölçüsü değildir.'}
        </p>

        {entity.issues.length > 0 && (
          <ul className="mt-2 space-y-1">
            {entity.issues.map((issue) => (
              <li key={issue} className="flex items-start gap-1 text-2xs text-warn">
                <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
                <span>{issue}</span>
              </li>
            ))}
          </ul>
        )}
      </header>

      <section className="surface surface-flat overflow-hidden">
        <h3 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">Paylar</h3>
        <OwnerPositionTable positions={positions} />
      </section>

      <section className="surface surface-flat overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
          <h3 className="text-base font-semibold text-fg">Pay giriş ve çıkışları</h3>
          {trackingSince && (
            <span
              className="text-2xs text-fg-subtle"
              title="Günlük kart kayıtlarının başladığı gün"
            >
              Kayıt {formatDate(trackingSince)} tarihinden beri
            </span>
          )}
        </div>
        <StakeMovesList moves={stakeMoves} trackingSince={trackingSince} showHolder={false} />
      </section>

      <section className="surface surface-flat overflow-hidden">
        <h3 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">
          Bu şirketlerdeki bildirimler
        </h3>
        <OwnershipMoves
          moves={moves}
          empty="Bu ortağın şirketleri için tapede ortaklık değişimi niteliğinde bir bildirim yok."
        />
      </section>

      {sources.length > 0 && (
        <footer className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-2xs text-fg-subtle">
          {sources.map((source) => (
            <span key={source.kind} className="inline-flex items-center gap-1">
              Kaynak:{' '}
              {source.url ? (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-fg-muted hover:underline"
                >
                  {source.label}
                  <ExternalLink className="h-2.5 w-2.5" aria-hidden="true" />
                </a>
              ) : (
                source.label
              )}
              {source.as_of && <span>· {source.as_of}</span>}
            </span>
          ))}
        </footer>
      )}
    </div>
  );
}
