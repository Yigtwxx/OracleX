'use client';

import type { CSSProperties } from 'react';
import type { ChainRow } from '@/lib/api';
import {
  CADENCE_ALERT_THRESHOLD,
  CHAIN_TINT,
  LOAD_BASIS_DETAIL,
  LOAD_BASIS_LABEL,
  NO_READING,
  cadenceDeviation,
  formatCount,
  formatDuration,
  formatUsd,
} from '@/lib/chain-format';

interface ChainCardProps {
  chain: ChainRow;
  /** The page's shared clock. Every card's ring reads this rather than its own. */
  now: number;
  isSelected: boolean;
  onSelect: (key: string) => void;
}

const RING_SIZE = 46;
const RING_RADIUS = 19;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * How far past its target a chain may run before the ring stops filling.
 *
 * The ring is a progress indicator, and progress past 100% is not a thing it
 * can draw — but a chain that has genuinely stalled must not look identical to
 * one that is exactly on time. So the ring saturates and the colour changes,
 * which is what separates the two.
 */
const RING_OVERRUN_LIMIT = 1;

/**
 * The slowest cadence at which "time since the last block" is still a thing
 * this page can observe — and the reason six of the eight cards do not get a
 * ring at all.
 *
 * The board is cached for ten seconds, so the newest block it knows about may
 * already be ten seconds old. On Bitcoin, where blocks are ten minutes apart,
 * that is a rounding error. On Arbitrum, where they are a quarter of a second
 * apart, it is not: the first draft of this card counted up from the newest
 * known Arbitrum block and settled at around nine seconds, drawn in the amber
 * that means overdue. Arbitrum was not overdue. It had produced roughly thirty
 * six blocks in that window, and the card was reporting the age of our
 * information as though it were the age of the chain's last block.
 *
 * No poll interval fixes this, because the shortfall is the interval. So the
 * ring is drawn only where the cadence is longer than the staleness it is
 * measured against, and the faster chains show their block *rate* instead —
 * which is a real measurement, and the one that means something at that speed.
 */
const RING_MIN_PERIOD_SECONDS = 10;

/**
 * How much of the elapsed time may be our own latency rather than the chain's.
 *
 * The board is cached for ten seconds, so the newest block it knows about can
 * be ten seconds old before the page has any way to hear about a newer one.
 * That is enough to matter on Ethereum: at a twelve-second cadence, a perfectly
 * healthy chain routinely reads as twenty-two seconds since its last block, and
 * colouring that amber would mark Ethereum overdue most of the time for a delay
 * that is ours.
 *
 * So the ring still *fills* over one period — that part is honest, it is
 * progress against the cadence — but it only turns amber once the block is late
 * by more than this window can account for.
 */
const STALENESS_ALLOWANCE_SECONDS = 10;

/** A block rate, in whichever unit does not read as a decimal fraction. */
function formatRate(blockTimeSeconds: number): string {
  const perSecond = 1 / blockTimeSeconds;
  if (perSecond >= 1) return `${perSecond.toFixed(1)}/s`;
  return `${(perSecond * 60).toFixed(0)}/m`;
}

/**
 * One chain, as a card: its cadence as a filling ring, then the three readings
 * that fit beside it.
 *
 * The ring is the point of the card and the reason this page needs no
 * websocket. It fills over the chain's own target block time against the
 * server's timestamp for the last block, and the page's clock ticks it several
 * times a second — so between two ten-second polls the card is continuously
 * moving, and moving *correctly*, because it is animating a real elapsed time
 * rather than a guess. When a poll brings a new height the ring drops back to
 * empty on its own, which is the beat the eye actually reads as "a block just
 * landed".
 *
 * Solana is the exception the design has to accommodate rather than hide: its
 * slots are not dated individually, so there is no instant to count from. Its
 * ring is not drawn at all and the card leads with throughput instead, which is
 * the honest substitute — see `elapsed` below.
 */
export default function ChainCard({ chain, now, isSelected, onSelect }: ChainCardProps) {
  const tint = CHAIN_TINT[chain.key] ?? 'var(--accent)';
  const deviation = cadenceDeviation(chain);
  const isSlow = deviation !== null && deviation > CADENCE_ALERT_THRESHOLD;

  // Measured cadence, not the protocol target, because the ring should fill at
  // the rate this chain is actually running — otherwise a chain running at half
  // speed shows a ring that completes and sits there, saying nothing.
  const period = chain.block_time_seconds ?? chain.target_block_seconds;

  // Whether this chain is slow enough for the count-up to mean anything. See
  // RING_MIN_PERIOD_SECONDS — the target is used rather than the measurement so
  // a chain does not flip between the two presentations as its cadence drifts.
  const canTimeBlocks =
    chain.last_block_at !== null && chain.target_block_seconds >= RING_MIN_PERIOD_SECONDS;

  // Null rather than zero when the chain publishes no per-block timestamp: a
  // ring stuck at empty would read as a chain that has produced nothing.
  const elapsed =
    canTimeBlocks && chain.last_block_at !== null ? (now - chain.last_block_at) / 1000 : null;
  const progress =
    elapsed === null || period <= 0 ? null : Math.min(elapsed / period, 1 + RING_OVERRUN_LIMIT);

  // Late by more than one period plus the window our own caching could account
  // for. A different claim from the cadence average being off, and the only one
  // a single missing block can support.
  const isOverdue = elapsed !== null && elapsed > period + STALENESS_ALLOWANCE_SECONDS;

  const ringColor = isOverdue ? 'var(--warn)' : tint;
  const dashOffset =
    progress === null ? RING_CIRCUMFERENCE : RING_CIRCUMFERENCE * (1 - Math.min(progress, 1));

  const load = chain.load;
  const fee = chain.fee;

  if (chain.error) {
    return (
      <div className="surface p-3 flex flex-col gap-1.5 opacity-70">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-down shrink-0" />
          <span className="text-sm font-semibold text-fg">{chain.name}</span>
        </div>
        <p className="text-2xs text-fg-subtle">Node unreachable — no reading this refresh.</p>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onSelect(chain.key)}
      aria-pressed={isSelected}
      className={`surface p-3 text-left w-full transition-colors ${
        isSelected ? 'border-line-strong' : 'hover:bg-surface-2'
      }`}
      style={{ '--chain-tint': tint } as CSSProperties}
    >
      <div className="flex items-start gap-3">
        {/* The ring, on the two chains slow enough to have one. `aria-hidden`
            because it is a redrawing of the cadence printed in text right
            beside it — announcing both would read the same fact twice, and a
            ring that repaints four times a second is a live region no screen
            reader should be handed. */}
        <div
          className="relative shrink-0 flex items-center justify-center"
          style={{ width: RING_SIZE, height: RING_SIZE }}
        >
          {canTimeBlocks ? (
            <>
              <svg width={RING_SIZE} height={RING_SIZE} aria-hidden className="-rotate-90">
                <circle
                  cx={RING_SIZE / 2}
                  cy={RING_SIZE / 2}
                  r={RING_RADIUS}
                  fill="none"
                  stroke="var(--line)"
                  strokeWidth="2.5"
                />
                {progress !== null && (
                  <circle
                    cx={RING_SIZE / 2}
                    cy={RING_SIZE / 2}
                    r={RING_RADIUS}
                    fill="none"
                    stroke={ringColor}
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeDasharray={RING_CIRCUMFERENCE}
                    strokeDashoffset={dashOffset}
                  />
                )}
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-2xs font-mono tabnum text-fg-muted">
                {elapsed === null ? NO_READING : `${Math.floor(elapsed)}s`}
              </span>
            </>
          ) : (
            // Too fast to time — the rate is what is left that is true. Drawn
            // flat rather than as a full ring, so it cannot be mistaken for a
            // countdown that has completed.
            <span
              className="text-xs font-mono tabnum"
              style={{ color: tint }}
              title={`Blocks arrive faster than this board refreshes, so there is no meaningful "time since the last block" — the rate is shown instead`}
            >
              {chain.block_time_seconds ? formatRate(chain.block_time_seconds) : NO_READING}
            </span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-semibold text-fg truncate">{chain.name}</span>
            <span
              className={`text-2xs font-mono tabnum shrink-0 ${
                isSlow ? 'text-warn' : 'text-fg-subtle'
              }`}
              title={
                deviation === null
                  ? undefined
                  : `Target ${formatDuration(chain.target_block_seconds)}, running ${
                      deviation >= 0 ? 'slow' : 'fast'
                    } by ${Math.abs(deviation * 100).toFixed(0)}%`
              }
            >
              {formatDuration(chain.block_time_seconds)}
            </span>
          </div>

          <div className="mt-0.5 text-2xs font-mono tabnum text-fg-subtle truncate">
            {chain.height === null ? NO_READING : `#${chain.height.toLocaleString('en-US')}`}
          </div>

          {/* Load. The basis label under the bar is not decoration: the same
              bar means gas used on Ethereum, unconfirmed backlog on Bitcoin
              and dropped slots on Solana, and those do not compare. */}
          <div className="mt-2">
            {load ? (
              <>
                <div
                  className="h-1 rounded-full bg-surface-2 overflow-hidden"
                  role="img"
                  aria-label={`${LOAD_BASIS_LABEL[load.basis]} ${load.percent}%`}
                  title={LOAD_BASIS_DETAIL[load.basis]}
                >
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(load.percent, 100)}%`,
                      background: tint,
                    }}
                  />
                </div>
                <div className="mt-1 flex items-baseline justify-between gap-2">
                  <span className="text-2xs text-fg-subtle truncate">
                    {LOAD_BASIS_LABEL[load.basis]}
                  </span>
                  <span className="text-2xs font-mono tabnum text-fg-muted shrink-0">
                    {load.percent.toFixed(0)}%
                  </span>
                </div>
              </>
            ) : (
              // Said outright rather than left blank. An empty slot where the
              // other seven cards have a bar reads as zero load.
              <p className="text-2xs text-fg-subtle">No capacity ceiling to measure against</p>
            )}
          </div>

          <div className="mt-2 flex items-baseline justify-between gap-2 border-t border-line pt-1.5">
            <span className="text-2xs text-fg-subtle">
              {chain.family === 'solana' && chain.throughput
                ? `${formatCount(chain.throughput.non_vote_tps)} tps`
                : `${formatCount(chain.tx_count)} txs`}
            </span>
            <span className="text-2xs font-mono tabnum text-fg-muted shrink-0">
              {fee?.transfer_native === 0 ? 'free' : formatUsd(fee?.transfer_usd)}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}
