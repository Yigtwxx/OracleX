'use client';

import { useCallback, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { AlertTriangle, ArrowLeft, RefreshCw } from 'lucide-react';
import type { OwnershipCategory } from '@/lib/api';
import { useOwnershipBoard, useOwnershipFlowNote } from '@/hooks/queries';
import CategoryFilter from './ownership/CategoryFilter';
import EntityCard from './ownership/EntityCard';
import EntityDetail from './ownership/EntityDetail';
import EntityRail from './ownership/EntityRail';
import LatestMovesStrip from './ownership/LatestMovesStrip';
import AssetOwnersPanel from './ownership/AssetOwnersPanel';
import ConsensusPanel from './ownership/ConsensusPanel';
import FlowNote from './ownership/FlowNote';
import WatchlistOverlap from './ownership/WatchlistOverlap';
import { CATEGORY_LABEL, formatDate } from './ownership/format';

/** Skeleton count chosen to fill the fold without reflowing when data lands. */
const SKELETON_CARDS = 8;

export default function OwnershipPage() {
  const board = useOwnershipBoard();
  const flowNote = useOwnershipFlowNote();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Which asset's owner list is open. Local rather than in the URL: it is a
  // lookup over the current view, not a place, and putting it in history would
  // make Back close a dialog instead of leaving the holder.
  const [assetLookup, setAssetLookup] = useState<string | null>(null);

  const activeEntityId = searchParams.get('entity');
  const activeCategory = (searchParams.get('category') as OwnershipCategory | null) ?? null;

  /**
   * URL is the single source of view state, so a detail pane is shareable and
   * Back does what Back should.
   *
   * `push` for selecting a holder — Back must return to the grid.
   * `replace` for filters — someone who tries four categories should not have
   * to press Back four times to leave.
   */
  const setParam = useCallback(
    (key: string, value: string | null, mode: 'push' | 'replace') => {
      const next = new URLSearchParams(searchParams.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      const query = next.toString();
      const url = query ? `${pathname}?${query}` : pathname;
      if (mode === 'push') router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const entities = useMemo(() => {
    const all = board.data?.entities ?? [];
    return activeCategory ? all.filter((e) => e.category === activeCategory) : all;
  }, [board.data, activeCategory]);

  const activeEntity = useMemo(
    () => board.data?.entities.find((e) => e.id === activeEntityId),
    [board.data, activeEntityId]
  );

  const failedSources = (board.data?.sources ?? []).filter((source) => !source.ok);
  const isDetail = Boolean(activeEntityId);

  // An outage renders as an outage. An empty grid would turn "we could not
  // reach the sources" into "nobody holds anything".
  if (board.isError && !board.data) {
    return (
      <div className="custom-scrollbar h-full overflow-y-auto p-4">
        <div className="surface mx-auto max-w-xl p-6 text-center">
          <p className="text-md font-medium text-fg">The ownership board is unavailable</p>
          <p className="mt-1 text-xs text-fg-muted">
            It is rebuilt once a day from public filings. If this is a fresh install, the first
            build may not have run yet.
          </p>
          <button
            type="button"
            onClick={() => board.refetch()}
            className="mt-3 rounded border border-line px-3 py-1.5 text-xs text-fg-muted transition-colors hover:text-fg"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-4">
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-3">
        <div className="flex items-center gap-3">
          {isDetail && (
            <button
              type="button"
              onClick={() => setParam('entity', null, 'push')}
              className="flex items-center gap-1.5 rounded border border-line px-2 py-1 text-2xs uppercase tracking-wide text-fg-subtle transition-colors hover:text-fg"
            >
              <ArrowLeft className="h-3 w-3" aria-hidden />
              Back
            </button>
          )}
          <div>
            <h1 className="text-lg font-semibold text-fg">Ownership</h1>
            <p className="text-xs text-fg-subtle">
              Who holds what, from public filings and public APIs
              {board.data?.last_refresh_at && (
                <> · updated {formatDate(board.data.last_refresh_at)}</>
              )}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={() => board.refetch()}
          disabled={board.isFetching}
          className="flex items-center gap-1.5 rounded border border-line px-2 py-1 text-2xs uppercase tracking-wide text-fg-subtle transition-colors hover:text-fg disabled:opacity-50"
        >
          <RefreshCw className={`h-3 w-3 ${board.isFetching ? 'animate-spin' : ''}`} aria-hidden />
          Refresh
        </button>
      </header>

      {board.data?.stale && (
        <p className="flex shrink-0 items-center gap-1.5 text-2xs text-warn">
          <AlertTriangle className="h-3 w-3" aria-hidden />
          Showing the last board that was built — today&apos;s refresh has not landed yet.
        </p>
      )}

      {isDetail ? (
        /* Split view. The rail keeps every holder reachable, so comparing two
           of them is a click rather than a round trip through the grid. */
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[240px_minmax(0,1fr)]">
          <div className="hidden min-h-0 lg:block">
            <EntityRail
              entities={board.data?.entities ?? []}
              activeId={activeEntityId as string}
              onSelect={(id) => setParam('entity', id, 'push')}
            />
          </div>
          <div className="min-h-0">
            <EntityDetail
              entityId={activeEntityId as string}
              fallback={activeEntity}
              onSelectAsset={setAssetLookup}
            />
          </div>
        </div>
      ) : (
        <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-[1600px] flex-col gap-4">
            {board.data && (
              <CategoryFilter
                counts={board.data.category_counts}
                active={activeCategory}
                onChange={(category) => setParam('category', category, 'replace')}
              />
            )}

            {board.data && (
              <LatestMovesStrip
                moves={board.data.latest_moves}
                // Every holder on its first observation: there is nothing to
                // compare against yet, which is different from nothing happening.
                baseline={board.data.entities.every((entity) => entity.last_move === null)}
              />
            )}

            {/* The quarter in prose, above the tables that enumerate it.
                Absent when no holder has a comparable filing, which is not the
                same as a quarter in which nobody traded. */}
            <FlowNote data={flowNote.data} />

            <WatchlistOverlap onSelectAsset={setAssetLookup} />

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {board.isLoading
                ? Array.from({ length: SKELETON_CARDS }, (_, i) => (
                    <div key={i} className="surface shimmer h-44" />
                  ))
                : entities.map((entity) => <EntityCard key={entity.id} entity={entity} />)}
            </div>

            {!board.isLoading && entities.length === 0 && (
              <p className="text-xs text-fg-subtle">
                Nothing tracked under{' '}
                {activeCategory ? CATEGORY_LABEL[activeCategory] : 'any category'} yet.
              </p>
            )}

            <ConsensusPanel onSelectAsset={setAssetLookup} />

            <footer className="flex flex-col gap-1 border-t border-line pt-3 text-2xs text-fg-subtle">
              {failedSources.length > 0 && (
                <p className="text-warn">
                  {failedSources.length} of {board.data?.sources.length} sources unavailable:{' '}
                  {failedSources.map((s) => s.kind).join(', ')}
                </p>
              )}
              <p>
                Compiled from public regulatory filings and public APIs. Figures are as reported and
                may be delayed or incomplete — a quarterly filing can be up to 45 days old. Not a
                complete picture of net worth, and not investment advice.
              </p>
            </footer>
          </div>
        </div>
      )}

      <AssetOwnersPanel
        symbol={assetLookup}
        onClose={() => setAssetLookup(null)}
        onSelectEntity={(id) => {
          setAssetLookup(null);
          setParam('entity', id, 'push');
        }}
      />
    </div>
  );
}
