'use client';

import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useChainAnomalies, useChainsBoard } from '@/hooks/queries';
import { useNow } from '@/hooks/useNow';
import BlockStream from '@/components/chains/BlockStream';
import ChainCard from '@/components/chains/ChainCard';
import AnomalyBanner from '@/components/chains/AnomalyBanner';
import DeviationBanner from '@/components/chains/DeviationBanner';
import EconomicsPanel from '@/components/chains/EconomicsPanel';
import FeeRacer from '@/components/chains/FeeRacer';
import FlowStrip from '@/components/chains/FlowStrip';
import { PanelSkeleton } from '@/components/ui/Panel';

/**
 * The Chains tab: how the networks the market settles on are running right now.
 *
 * The page owns the one query and the one clock; every panel below takes props
 * and nothing else. That is what lets a card click change which chain the block
 * stream draws without either component knowing the other exists — the same
 * arrangement the Live tab uses.
 *
 * The clock ticks four times a second rather than once. Every other countdown
 * in this app is measured in minutes, where a one-second tick is smooth enough,
 * but the cards here are drawing a ring that completes in two seconds on three
 * of the eight chains — at 1Hz that is four visible steps and reads as a stutter
 * rather than a sweep. Four times a second is the cheapest rate at which the
 * ring resolves as motion; it drives eight small SVG updates and nothing else.
 */
const CLOCK_INTERVAL_MS = 250;

export default function ChainsPage() {
  const board = useChainsBoard();
  const anomalies = useChainAnomalies();
  const now = useNow(CLOCK_INTERVAL_MS);

  // Ethereum by default: it is the chain whose blocks most reward being watched,
  // and the only one where fullness moves visibly from block to block.
  const [selectedKey, setSelectedKey] = useState('ethereum');

  const chains = board.data?.chains ?? [];
  const selected =
    chains.find((chain) => chain.key === selectedKey) ??
    chains.find((chain) => !chain.error) ??
    null;

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="max-w-[1600px] mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-semibold text-fg">Chains</h1>
            <p className="text-base text-fg-muted">
              Block cadence, fees and congestion across the networks the market settles on.
            </p>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {/* The server's own `as_of`, not the browser's fetch time — a board
                replayed from cache after an upstream failure must not be stamped
                with the moment it was handed over. */}
            {board.data?.as_of && (
              <span className="flex items-center gap-2">
                {board.data.stale && (
                  <span
                    title="Upstream unavailable — showing the last board that could be built"
                    className="px-1.5 py-0.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle"
                  >
                    Stale
                  </span>
                )}
                <span className="text-xs font-mono tabnum text-fg-subtle">
                  {new Date(board.data.as_of).toLocaleTimeString('en-GB')}
                </span>
              </span>
            )}
            <button
              onClick={() => board.refetch()}
              aria-label="Refresh the chains board"
              className="p-1.5 bg-surface border border-line rounded-md text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${board.isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {board.isError ? (
          // Reported rather than rendered as an empty board. Eight blank cards
          // would read as eight halted networks, which is a claim about the
          // world rather than a gap in the data.
          <div className="surface p-6 text-center">
            <p className="text-base text-fg">The chains board is unavailable.</p>
            <p className="mt-1 text-sm text-fg-subtle">
              None of the network providers could be reached.
            </p>
            <button
              onClick={() => board.refetch()}
              className="mt-3 px-3 py-1.5 bg-surface-2 border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              Try again
            </button>
          </div>
        ) : board.isLoading ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
              {Array.from({ length: 8 }, (_, index) => (
                <div key={index} className="surface h-[7.5rem] shimmer" />
              ))}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_22rem] gap-3">
              <div className="h-64">
                <PanelSkeleton />
              </div>
              <div className="h-64">
                <PanelSkeleton />
              </div>
            </div>
          </div>
        ) : (
          <>
            <DeviationBanner chains={chains} />

            {/* Above the two-column grid further down, so its hand-tuned column
                heights are untouched — and, like the banner above, absent
                entirely when there is nothing unusual to report. */}
            <AnomalyBanner report={anomalies.data} />

            {/* Four across at xl rather than three: eight chains split evenly
                into two rows, and an odd column count would leave the last row
                two-thirds empty at every width. */}
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
              {chains.map((chain) => (
                <ChainCard
                  key={chain.key}
                  chain={chain}
                  now={now}
                  isSelected={selected?.key === chain.key}
                  onSelect={setSelectedKey}
                />
              ))}
            </div>

            {/* The stream takes the wide column because it is the only panel
                whose reading depends on width — ten bars need room to be
                compared. The two right-hand panels are lists and do not. */}
            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_22rem] gap-3">
              {/* Every panel here carries an explicit height rather than being
                  left to the grid, and the four are set to add up: 19+26 on the
                  left and 33+12 on the right both come to 45rem, so the columns
                  end level. Left to itself the row stretches to whichever side
                  is taller and every panel inside grows with it — the block
                  strip ended up 500px tall around a 128px chart, with the panel
                  below it pushed off the fold.

                  Two of the four are load-bearing rather than chosen to fit.
                  26rem on the fee table is what holds all eight rows without
                  scrolling — at 19rem it cut off after seven, and the row it hid
                  was Bitcoin's, the most expensive of the eight. A cost
                  comparison that scrolls its own extreme out of view is not
                  making the comparison. 33rem on Schedules is what reaches the
                  Solana block: at 24rem the whole section sat below the fold of
                  a panel that gave no sign there was more under it. */}
              <div className="space-y-3 min-w-0">
                <div className="h-[19rem]">
                  {selected && <BlockStream chain={selected} now={now} />}
                </div>
                <div className="h-[26rem]">
                  <FeeRacer chains={chains} />
                </div>
              </div>

              <div className="space-y-3">
                <div className="h-[33rem]">
                  <EconomicsPanel chains={chains} now={now} />
                </div>
                <div className="h-[12rem]">
                  {board.data && <FlowStrip flows={board.data.flows} />}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
