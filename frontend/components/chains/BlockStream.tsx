'use client';

import type { ChainBlock, ChainRow } from '@/lib/api';
import Panel from '@/components/ui/Panel';
import {
  CHAIN_TINT,
  NO_READING,
  formatCount,
  formatDuration,
  shortenHash,
  superscript,
} from '@/lib/chain-format';

interface BlockStreamProps {
  chain: ChainRow;
  now: number;
}

/**
 * The selected chain's recent blocks, newest first, each drawn as a column
 * whose height is how full it was.
 *
 * The bars are the panel's argument: a list of heights and transaction counts
 * is a table, but ten columns side by side show congestion *arriving* — you can
 * see the run of half-empty blocks end and the full ones start, which is the
 * one thing a single "74%" reading cannot tell you.
 *
 * Three chains get a different column, and each difference is a fact about the
 * chain rather than a fallback:
 *
 * - **Arbitrum and TRON** publish no capacity a block can be full of, so their
 *   columns are drawn hollow at a fixed height. Solid bars scaled to nothing
 *   would claim a measurement; empty ones would claim an idle chain.
 * - **Solana** streams groups of slots rather than single blocks, because ten
 *   of its slots span four seconds. Each column is split into one segment per
 *   slot, lit where a block was produced — so the grouping is visible in the
 *   drawing itself, and a skipped slot is a gap you can point at rather than a
 *   percentage.
 */
export default function BlockStream({ chain, now }: BlockStreamProps) {
  const tint = CHAIN_TINT[chain.key] ?? 'var(--accent)';
  const bucketSlots = chain.stream_bucket_slots ?? null;
  const isBucketed = bucketSlots !== null;
  const hasFill = chain.blocks.some((block) => block.fill_percent !== null);

  // The hash notation needs saying once: a superscript on a zero is not a
  // convention anyone should have to guess at, and on Bitcoin the number it
  // carries is the block's proof of work rather than formatting.
  const hashNote = 'Labels below are the block hash; 0ⁿ counts the leading zeros dropped.';

  const footnote = isBucketed
    ? `Each bar is ${bucketSlots} scheduled slots, one segment each — lit where a block was produced. ${hashNote}`
    : hasFill
      ? `Bar height is how full the block was, newest on the left. ${hashNote}`
      : `This chain publishes no block capacity, so height is uniform. ${hashNote}`;

  return (
    <Panel
      title={isBucketed ? `${chain.name} slots` : `${chain.name} blocks`}
      action={
        <span className="text-2xs font-mono tabnum text-fg-subtle">
          {formatDuration(chain.block_time_seconds)} avg
          {chain.cadence_span_seconds
            ? ` · over ${formatDuration(chain.cadence_span_seconds)}`
            : ''}
        </span>
      }
      footnote={footnote}
    >
      {chain.blocks.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="text-base text-fg-muted">No blocks returned this refresh.</p>
          <p className="mt-1 text-xs text-fg-subtle">
            The chain reported a height, but its node did not serve the block range.
          </p>
        </div>
      ) : (
        <div className="p-4">
          {/* 40px taller than it started: the column now carries a label above
              the bar and the hash below it, and both eat into the same box the
              bar is sized against. */}
          <div className="flex items-end gap-1.5 h-40">
            {chain.blocks.map((block) => (
              <BlockColumn key={block.height} block={block} chain={chain} tint={tint} now={now} />
            ))}
          </div>

          <div className="mt-2 flex items-center justify-between gap-2 text-2xs font-mono tabnum text-fg-subtle">
            <span>
              #{chain.blocks[0].height.toLocaleString('en-US')}
              {chain.blocks[0].timestamp_ms !== null &&
                ` · ${formatDuration((now - chain.blocks[0].timestamp_ms) / 1000)} ago`}
            </span>
            <span>
              {chain.blocks.length > 1
                ? `#${chain.blocks[chain.blocks.length - 1].height.toLocaleString('en-US')}`
                : NO_READING}
            </span>
          </div>
        </div>
      )}
    </Panel>
  );
}

function BlockColumn({
  block,
  chain,
  tint,
  now,
}: {
  block: ChainBlock;
  chain: ChainRow;
  tint: string;
  now: number;
}) {
  const fill = block.fill_percent;
  const scheduled = block.slots_scheduled;
  const produced = block.slots_produced;
  const isBucket = scheduled !== undefined && produced !== undefined;
  const ageSeconds = block.timestamp_ms === null ? null : (now - block.timestamp_ms) / 1000;
  const short = shortenHash(block.hash, chain.hash_height_prefix_chars ?? 0);

  // Floored at 6% so a nearly empty block is still a visible column rather than
  // a line the eye reads as a gap in the chain. Buckets are exempt: they run
  // full height and carry their reading in the segments instead.
  const heightPercent = isBucket ? 100 : fill === null ? 55 : Math.max(6, Math.min(fill, 100));

  const title = [
    isBucket
      ? `${produced} of ${scheduled} slots produced, ending at ${block.height.toLocaleString('en-US')}`
      : `Block ${block.height.toLocaleString('en-US')}`,
    !isBucket && fill !== null ? `${fill.toFixed(1)}% full` : null,
    block.tx_count === null ? null : `${formatCount(block.tx_count)} transactions`,
    ageSeconds === null ? null : `${formatDuration(ageSeconds)} ago`,
    // The full hash lives here rather than under the bar, where only six of its
    // characters fit. The label is the handle; this is the value.
    short ? short.full : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <a
      href={`${chain.explorer_block_url}${block.height}`}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex-1 min-w-0 flex flex-col justify-end h-full"
      title={title}
    >
      <span className="mb-1 text-2xs font-mono tabnum text-fg-subtle text-center truncate">
        {/* A bucket has no transaction count to show — the only route to one is
            downloading every signature in every slot. Its own production count
            is the honest label, and the more useful one. */}
        {isBucket ? `${produced}/${scheduled}` : formatCount(block.tx_count)}
      </span>

      {/* The bar's own track. Its height has to be what the two labels leave
          behind rather than the column's full height — the bar is sized as a
          percentage, so measuring it against a box the labels also sit in would
          push a 100%-full block past the bottom of the panel. `min-h-0` is what
          lets this flex child actually shrink to the leftover space. */}
      <span className="flex-1 min-h-0 w-full flex flex-col justify-end">
        {isBucket ? (
          // Newest slot at the top, so a run of skips reads downward from the
          // end of the bucket the way the eye scans it.
          <span
            className="w-full flex flex-col-reverse gap-px group-hover:opacity-80 transition-opacity"
            style={{ height: `${heightPercent}%` }}
          >
            {Array.from({ length: scheduled }, (_, index) => (
              <span
                key={index}
                className="flex-1 rounded-[1px]"
                style={{
                  background: index < produced ? tint : 'var(--surface-2)',
                }}
              />
            ))}
          </span>
        ) : (
          <span
            className="w-full rounded-sm transition-[height,opacity] duration-500 group-hover:opacity-80"
            style={{
              height: `${heightPercent}%`,
              // Chains with no ceiling are drawn hollow, so a uniform column
              // cannot be mistaken for a measured one.
              background: fill === null ? 'transparent' : tint,
              border: fill === null ? `1px solid ${tint}` : undefined,
            }}
          />
        )}
      </span>

      {/* The block's identity, under its column. The stripped zero-run is set
          apart from the digest rather than merged into one string: on Bitcoin
          it is the block's proof of work and worth reading, on TRON it is
          padding around a height and worth ignoring, and they should not look
          like the same characters. */}
      <span className="mt-1 text-2xs font-mono text-fg-subtle text-center truncate">
        {short ? (
          <>
            {short.zeros > 0 && <span className="opacity-50">0{superscript(short.zeros)}</span>}
            {short.digest}
          </>
        ) : (
          NO_READING
        )}
      </span>
    </a>
  );
}
