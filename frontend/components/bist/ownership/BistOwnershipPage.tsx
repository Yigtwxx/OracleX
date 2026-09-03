'use client';

import { AlertTriangle, ArrowLeft } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useMemo } from 'react';

import StatusMessage from '@/components/ui/StatusMessage';
import { useBistOwnershipBoard, useBistOwnershipNote } from '@/hooks/useBist';
import type { BistHolderCategory } from '@/lib/bist-api';
import { formatCompactTry, formatDate } from '@/lib/bist-format';
import { boardSummary, filterByCategory, isHolderCategory } from '@/lib/bist-ownership';
import BistPageShell from '../BistPageShell';
import BistOwnershipNote from './BistOwnershipNote';
import MetricTile from '../MetricTile';
import OwnerCard from './OwnerCard';
import OwnerCategoryChips from './OwnerCategoryChips';
import OwnerDetail from './OwnerDetail';
import OwnerRail from './OwnerRail';
import OwnershipMoves from './OwnershipMoves';
import StakeMovesList from './StakeMovesList';

/**
 * Ortaklık — who holds the XU100.
 *
 * The view lives in the URL, as on the global `/ownership` page: `?entity=`
 * opens a holder (pushed, so Back returns to the grid) and `?category=`
 * narrows the grid (replaced, so filters do not stack in history). A company
 * page links here with `?entity=`, and this page links back to company
 * pages from every stake, so the two surfaces are one loop.
 */
export default function BistOwnershipPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const entityId = params.get('entity');
  const categoryParam = params.get('category');
  const category: BistHolderCategory | null = isHolderCategory(categoryParam)
    ? categoryParam
    : null;

  const setParam = useCallback(
    (key: string, value: string | null, mode: 'push' | 'replace') => {
      const next = new URLSearchParams(params.toString());
      if (value === null) next.delete(key);
      else next.set(key, value);
      const query = next.toString();
      const href = query ? `${pathname}?${query}` : pathname;
      if (mode === 'push') router.push(href);
      else router.replace(href);
    },
    [params, pathname, router]
  );

  const { data, isLoading, isError, error } = useBistOwnershipBoard();
  const status = (error as { status?: number } | null)?.status;
  // Only once the board itself is there: the note describes the board, and
  // a paragraph over a 503 would be commentary on a page that does not exist.
  const note = useBistOwnershipNote(!!data);

  const visible = useMemo(
    () => (data ? filterByCategory(data.entities, category) : []),
    [data, category]
  );
  const summary = data ? boardSummary(data) : null;

  return (
    <BistPageShell
      title="Ortaklık"
      description="XU100'ü kim tutuyor — kamu, holdingler, yabancı ortaklar ve fonlar, %5 üzeri pay tabloları ve fon raporlarından, güncel piyasa değeriyle."
      action={
        data && (
          <span className="flex items-center gap-2 text-2xs text-fg-subtle">
            {data.stale && (
              <span className="rounded border border-warn/60 px-1.5 py-0.5 text-warn">
                pano eski
              </span>
            )}
            <span>{formatDate(data.as_of)}</span>
          </span>
        )
      }
      ribbon={
        summary && (
          <div className="grid gap-2 sm:grid-cols-4">
            <MetricTile
              label="İzlenen ortak"
              value={summary.entities}
              note={`${summary.withData} tanesinde pay var`}
            />
            <MetricTile
              label="Değerlenen toplam"
              value={summary.totalValued === null ? '—' : formatCompactTry(summary.totalValued)}
              note="Yalnızca fiyatlanabilen paylar"
            />
            <MetricTile label="Kapsam" value={summary.coverage} note="Okunan şirket kartı" />
            <MetricTile
              label="Son bildirim"
              value={data?.latest_moves[0]?.ticker ?? '—'}
              note={data?.latest_moves[0]?.event_label ?? 'Tapede ortaklık bildirimi yok'}
            />
          </div>
        )
      }
    >
      {isLoading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="surface shimmer h-40" />
          ))}
        </div>
      ) : isError || !data ? (
        <div className="surface">
          <StatusMessage icon={AlertTriangle}>
            {status === 503
              ? 'Ortaklık panosu henüz oluşturulmadı. Sunucu açılışında yüz şirket kartı sırayla okunur; birkaç dakika içinde hazır olur.'
              : 'Ortaklık panosu alınamadı.'}
          </StatusMessage>
        </div>
      ) : entityId ? (
        <div className="space-y-3">
          <BistOwnershipNote data={note.data} isLoading={note.isLoading && !note.data} />
          <button
            type="button"
            onClick={() => setParam('entity', null, 'push')}
            className="inline-flex items-center gap-1.5 text-sm text-fg-muted transition-colors hover:text-fg"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Tüm ortaklar
          </button>
          {/* The rail only from `lg` up: under that it would sit above the
              detail as a full-width list of fifty rows, pushing the holder the
              reader asked for below the fold. Back to the grid is one click
              either way. */}
          <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
            <div className="hidden lg:block">
              <OwnerRail
                entities={data.entities}
                activeId={entityId}
                onSelect={(id) => setParam('entity', id, 'replace')}
              />
            </div>
            <OwnerDetail entityId={entityId} />
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <BistOwnershipNote data={note.data} isLoading={note.isLoading && !note.data} />
          <OwnerCategoryChips
            counts={data.category_counts}
            active={category}
            onChange={(next) => setParam('category', next, 'replace')}
          />

          {data.latest_stake_moves.length > 0 && (
            <section className="surface surface-flat overflow-hidden">
              <h2 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">
                Son pay giriş ve çıkışları
              </h2>
              <StakeMovesList
                moves={data.latest_stake_moves}
                trackingSince={data.tracking_since}
                limit={6}
              />
            </section>
          )}

          {data.latest_moves.length > 0 && (
            <section className="surface surface-flat overflow-hidden">
              <h2 className="border-b border-line px-3 py-2 text-base font-semibold text-fg">
                Son ortaklık bildirimleri
              </h2>
              <OwnershipMoves moves={data.latest_moves} limit={6} empty="" />
            </section>
          )}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {visible.map((entity) => (
              <OwnerCard
                key={entity.id}
                entity={entity}
                onOpen={(id) => setParam('entity', id, 'push')}
              />
            ))}
          </div>

          <footer className="space-y-1 text-2xs text-fg-subtle">
            {data.sources
              .filter((source) => !source.ok)
              .map((source) => (
                <p key={source.kind} className="text-warn">
                  {source.kind === 'isyatirim_shareholders' ? 'İş Yatırım' : 'KAP fon raporları'}:{' '}
                  {source.message ?? 'kaynak yanıt vermedi'}
                </p>
              ))}
            <p>
              Paylar İş Yatırım şirket kartlarındaki %5 üzeri ortak tablolarından, fon pozisyonları
              KAP aylık portföy raporlarından okunur. Değerler pay oranı × güncel piyasa değeridir;
              bir ortağın gerçek servetini değil, bu endeksteki görünür payını gösterir. Bir ortak
              için 13F benzeri tam portföy açıklaması Türkiye&apos;de yoktur.
            </p>
          </footer>
        </div>
      )}
    </BistPageShell>
  );
}
