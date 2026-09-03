'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import {
  usePolymarketAnalysis,
  usePolymarketAnalysisJob,
  usePolymarketOrigin,
  usePolymarketOriginJob,
  useStartPolymarketOrigin,
  usePolymarketBoard,
  usePolymarketMap,
  usePolymarketMarket,
  useStartPolymarketAnalysis,
} from '@/hooks/queries';
import { useNow } from '@/hooks/useNow';
import Modal from '@/components/ui/Modal';
import { PanelSkeleton } from '@/components/ui/Panel';
import MarketCard from '@/components/polymarket/MarketCard';
import MarketDetail from '@/components/polymarket/MarketDetail';
import AnalysisPanel from '@/components/polymarket/AnalysisPanel';
import OriginPanel from '@/components/polymarket/OriginPanel';
// Loaded only when the map is opened. ECharts and the country outlines are
// ~370KB, and the map is collapsed by default — paying for it on every visit to
// the board would be most of this route's bundle spent on a panel most readers
// never expand.
const WorldMap = dynamic(() => import('@/components/polymarket/WorldMap'), {
  ssr: false,
  loading: () => (
    <div className="w-full aspect-[2/1] min-h-[360px] max-h-[580px] shimmer rounded-lg" />
  ),
});
import { categoryLabel } from '@/lib/polymarket-format';

/**
 * The Polymarket tab: what people are betting happens next, and why.
 *
 * A grid of cards rather than a list beside a fixed panel. The board is sixty
 * questions with no natural ordering beyond volume, and a reader scans it
 * looking for the one they have an opinion about — which is a browsing motion,
 * not a comparison. A permanent detail pane would spend half the width on
 * whichever market happened to be first.
 *
 * Clicking a card brings it forward in a dialog over a lightly blurred board.
 * The blur is slight on purpose: the reader chose this card out of a grid and
 * should still see the grid it came from, so the dialog reads as an expansion
 * rather than as a new page.
 *
 * The clock ticks every thirty seconds, not every second. Countdowns here are
 * rendered at minute granularity at their finest, so a faster tick buys no
 * accuracy — and it is shared by every card, so each tick re-renders the whole
 * board. At sixty cards that was a visible stutter for a label that changes on
 * a handful of them.
 */
const CLOCK_INTERVAL_MS = 30_000;

const CATEGORY_ORDER = ['politics', 'geopolitics', 'macro', 'crypto', 'sports', 'general'];

export default function PolymarketPage() {
  const board = usePolymarketBoard();
  const map = usePolymarketMap();
  const [showMap, setShowMap] = useState(false);
  const now = useNow(CLOCK_INTERVAL_MS);
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const [category, setCategory] = useState<string>('all');
  // Job ids per slug rather than one "current" id: the panel reads a key derived
  // from the open market, so a verdict arriving after the reader moved on cannot
  // render under the wrong question.
  const [jobIds, setJobIds] = useState<Record<string, string>>({});
  // The origin trace is its own run with its own id. Same slug key, same reason:
  // it is the shorter of the two and routinely lands while the verdict is still
  // being written, so it must be able to render without one.
  const [originJobIds, setOriginJobIds] = useState<Record<string, string>>({});

  const markets = board.data?.markets ?? [];
  const detail = usePolymarketMarket(openSlug);

  // Only offer a filter for categories the board actually has. A chip that
  // always returns nothing teaches the reader the filter is broken.
  const present = CATEGORY_ORDER.filter((key) => markets.some((m) => m.category === key));
  const shown = category === 'all' ? markets : markets.filter((m) => m.category === category);

  const openMarket = markets.find((m) => m.slug === openSlug) ?? null;

  const startAnalysis = useStartPolymarketAnalysis();
  const analysisJob = usePolymarketAnalysisJob(openSlug ? jobIds[openSlug] : undefined);
  const analysis = usePolymarketAnalysis(openSlug);

  const startOrigin = useStartPolymarketOrigin();
  const originJob = usePolymarketOriginJob(openSlug ? originJobIds[openSlug] : undefined);
  const origin = usePolymarketOrigin(openSlug);

  // One click, two runs. Neither is chained to the other: the origin trace
  // answers a different question on a different budget, and holding it back
  // until the verdict published would hide a result that was ready first.
  const runAnalysis = () => {
    if (!openSlug) return;
    startAnalysis.mutate(openSlug, {
      onSuccess: (job) => setJobIds((prev) => ({ ...prev, [job.slug]: job.jobId })),
    });
    startOrigin.mutate(openSlug, {
      onSuccess: (job) => setOriginJobIds((prev) => ({ ...prev, [job.slug]: job.jobId })),
    });
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="max-w-[1600px] mx-auto space-y-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-semibold text-fg">Polymarket</h1>
            <p className="text-base text-fg-muted">
              What people are betting happens next, priced by the money behind it.
            </p>
          </div>

          {board.data?.stale && (
            <span className="text-2xs text-warn shrink-0">
              Replayed from cache, {board.data.age_seconds}s old
            </span>
          )}
        </div>

        <div>
          <button
            type="button"
            onClick={() => setShowMap((v) => !v)}
            aria-expanded={showMap}
            className="text-xs px-2.5 py-1 rounded-full border border-line text-fg-muted hover:text-fg transition-colors"
          >
            {showMap ? 'Hide map' : 'Show map'}
          </button>
          {/* Collapsed by default: the map is a second way of reading the same
              board, and opening the tab straight onto it would put a 420px
              graphic between the reader and the questions they came for. */}
          {showMap &&
            (map.data ? (
              <div className="mt-3">
                <WorldMap data={map.data} onSelectMarket={setOpenSlug} />
              </div>
            ) : (
              <div className="mt-3 w-full aspect-[2/1] min-h-[360px] max-h-[580px] shimmer rounded-lg" />
            ))}
        </div>

        <div className="flex items-center gap-1.5 flex-wrap">
          {['all', ...present].map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setCategory(key)}
              aria-pressed={category === key}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                category === key
                  ? 'border-line-strong text-fg bg-surface-2'
                  : 'border-line text-fg-muted hover:text-fg'
              }`}
            >
              {key === 'all' ? 'All' : categoryLabel(key)}
            </button>
          ))}
        </div>

        {board.isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="h-40">
                <PanelSkeleton />
              </div>
            ))}
          </div>
        ) : shown.length === 0 ? (
          <p className="text-xs text-fg-muted">No open markets could be read right now.</p>
        ) : (
          <div className="grid-virtual grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3">
            {shown.map((market) => (
              <MarketCard key={market.market_id} market={market} nowMs={now} onOpen={setOpenSlug} />
            ))}
          </div>
        )}
      </div>

      <Modal
        isOpen={Boolean(openSlug)}
        onClose={() => setOpenSlug(null)}
        title={openMarket?.question ?? 'Market'}
        maxWidth="max-w-3xl"
        scrimClassName="bg-black/40 backdrop-blur-[2px]"
      >
        {detail.isLoading || !detail.data ? (
          <div className="h-64 shimmer" />
        ) : (
          <>
            <MarketDetail detail={detail.data} />
            <div className="px-4 pb-4 pt-3 border-t border-line">
              <OriginPanel
                report={origin.data}
                job={originJob.data}
                isStarting={startOrigin.isPending}
              />
              <AnalysisPanel
                verdict={analysis.data}
                job={analysisJob.data}
                isStarting={startAnalysis.isPending}
                onRun={runAnalysis}
              />
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
