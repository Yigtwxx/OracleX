import type { ChainLoadBasis, ChainRow } from '@/lib/api';

/**
 * Formatting for the Chains board.
 *
 * Collected here rather than inlined because the same three problems recur on
 * every panel, and solving them per component is how a board ends up printing
 * the same quantity two different ways one row apart.
 *
 * The recurring problem is range. Fees on this board span from $0.0000004 on OP
 * Mainnet to $0.09 on Bitcoin — five orders of magnitude in one column — and
 * cadence spans 0.25 seconds to ten minutes. A single `toFixed` is wrong at one
 * end or the other whichever digit count it picks.
 */

/** Every unmeasured reading prints as this. One em dash, never a zero. */
export const NO_READING = '—';

/**
 * A currency amount whose magnitude is not known in advance.
 *
 * Precision follows the number rather than the column: sub-cent fees keep
 * enough significant figures to be compared against each other, and anything
 * above a dollar drops to the two decimals money is normally written in.
 * Printing OP Mainnet's fee at two decimals would render it "$0.00", which
 * reads as free and is the one thing the FeeRacer must never say by accident.
 */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_READING;
  if (value === 0) return '$0';
  const abs = Math.abs(value);
  if (abs >= 1) return `$${value.toFixed(2)}`;
  if (abs >= 0.01) return `$${value.toFixed(3)}`;
  if (abs >= 0.0001) return `$${value.toFixed(5)}`;
  // Down to a millionth stays a plain decimal. "$0.000042" is eight characters
  // and reads at a glance; "$4.2e-5" is shorter and does not — an exponent in a
  // fee column makes the reader stop and count places, which is the one thing
  // the column exists to save them from.
  if (abs >= 0.000001) return `$${value.toFixed(6)}`;
  // Past a millionth the decimal really is all leading zeros, and the exponent
  // carries the magnitude better than "$0.0000000042" does.
  return `$${value.toExponential(1)}`;
}

/** A large count, abbreviated. Used for transaction counts and addresses. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_READING;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toLocaleString('en-US');
}

/** A signed dollar flow, abbreviated, with its direction kept explicit. */
export function formatFlowUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_READING;
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

/**
 * A block cadence, in the unit that suits its scale.
 *
 * Arbitrum's 0.25s and Bitcoin's ten minutes are the same quantity, and no
 * single unit reads well for both — "600.0s" is arithmetic the reader has to
 * do, and "0.0m" is nothing at all.
 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return NO_READING;
  if (seconds < 1) return `${seconds.toFixed(2)}s`;
  if (seconds < 100) return `${seconds.toFixed(1)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1)}m`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

/** A countdown to a future instant, coarse on purpose — these are estimates. */
export function formatCountdown(targetMs: number | null | undefined, nowMs: number): string {
  if (targetMs === null || targetMs === undefined || !Number.isFinite(targetMs)) {
    return NO_READING;
  }
  const seconds = Math.max(0, (targetMs - nowMs) / 1000);
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/** How many characters of a block hash the stream labels a column with. */
export const HASH_DIGEST_CHARS = 6;

const SUPERSCRIPT_DIGITS = '⁰¹²³⁴⁵⁶⁷⁸⁹';

/** A count rendered as superscript digits, so it can sit inline without a gap. */
export function superscript(value: number): string {
  return String(value)
    .split('')
    .map((digit) => SUPERSCRIPT_DIGITS[Number(digit)] ?? digit)
    .join('');
}

export interface ShortHash {
  /** Leading zeros that were stripped. Zero on chains that have none. */
  zeros: number;
  /** The first {@link HASH_DIGEST_CHARS} characters after them. */
  digest: string;
  /** The full hash, for the tooltip. */
  full: string;
}

/**
 * A block hash, shortened to something that fits under a column.
 *
 * Leading zeros are counted and stripped rather than shown, because on two of
 * the eight chains they are all a plain truncation would ever show. A Bitcoin
 * hash opens with about nineteen of them, so the first six characters of every
 * block in the strip are `000000` — ten identical labels identifying nothing.
 * TRON is the same for a different reason: its `blockID` begins with the block
 * number zero-padded into eight bytes, so a low height is mostly padding.
 *
 * The count is kept rather than discarded because it is not the same fact on
 * the two chains, and on one of them it is real information. Bitcoin's leading
 * zeros *are* its proof of work — a block with twenty of them took more work
 * than one with eighteen, and that number moves block to block. TRON's are an
 * artefact of padding and move only as the height grows. Showing the count lets
 * the first be read and the second be ignored; hiding it would flatten them
 * into the same silence.
 *
 * `0x` is dropped first: every EVM hash carries it, so it distinguishes nothing
 * and costs two of the six characters that do.
 *
 * `skipChars` handles the one chain where leading zeros are not the whole
 * problem. TRON's `blockID` is its header hash with the first eight bytes
 * overwritten by the zero-padded block number, so sixteen of its characters are
 * a height the column already prints in decimal — and at current heights only
 * the last of those sixteen changes from block to block. Stripping zeros alone
 * left `5179b7` on ten consecutive bars. The registry carries the count to skip;
 * see `Chain.hash_height_prefix_chars`.
 */
export function shortenHash(hash: string | null | undefined, skipChars = 0): ShortHash | null {
  if (!hash) return null;
  const unprefixed = hash.startsWith('0x') || hash.startsWith('0X') ? hash.slice(2) : hash;
  // Guarded rather than trusted: a shorter hash than the skip would otherwise
  // leave nothing at all, and a blank label is worse than a repeated one.
  const body = unprefixed.length > skipChars ? unprefixed.slice(skipChars) : unprefixed;
  if (!body) return null;

  let zeros = 0;
  while (zeros < body.length && body[zeros] === '0') zeros += 1;

  // An all-zero hash is not a thing any of these chains produces, but a
  // truncation that returned an empty string would render as a missing label
  // rather than an odd one.
  const remainder = zeros === body.length ? body : body.slice(zeros);

  return {
    zeros,
    digest: remainder.slice(0, HASH_DIGEST_CHARS),
    full: hash,
  };
}

/** Hashrate, which arrives in hashes per second and is only ever read in EH/s. */
export function formatHashrate(hashesPerSecond: number | null | undefined): string {
  if (
    hashesPerSecond === null ||
    hashesPerSecond === undefined ||
    !Number.isFinite(hashesPerSecond)
  ) {
    return NO_READING;
  }
  return `${(hashesPerSecond / 1e18).toFixed(0)} EH/s`;
}

/** What a load bar is actually measuring, spelled out under it. */
export const LOAD_BASIS_LABEL: Record<ChainLoadBasis, string> = {
  block_fullness: 'block fullness',
  fee_contested_backlog: 'contested backlog',
  skipped_slots: 'skipped slots',
};

/**
 * The longer form, for a tooltip. Each says what the number is *not*, because
 * that is the part a reader would otherwise get wrong.
 */
export const LOAD_BASIS_DETAIL: Record<ChainLoadBasis, string> = {
  block_fullness: 'Gas used against the block gas limit, on the newest block.',
  fee_contested_backlog:
    'Blocks of mempool still bidding above the economy fee. Excludes the queued dust that will not confirm at any price, which is most of it.',
  skipped_slots: 'Scheduled slots no leader produced. Solana has no mempool to queue behind.',
};

/**
 * How far off its own target a chain's cadence is running, as a fraction.
 *
 * Positive is slow. Returns null rather than 0 when either side is unknown, so
 * "on time" and "unmeasured" stay distinguishable.
 */
export function cadenceDeviation(chain: ChainRow): number | null {
  const { block_time_seconds: actual, target_block_seconds: target } = chain;
  if (actual === null || !Number.isFinite(actual) || !target) return null;
  return (actual - target) / target;
}

/**
 * Whether a cadence deviation is worth colouring.
 *
 * Generous on purpose. Block production is a random process on every chain
 * here, and Bitcoin's especially: ten blocks can average seven minutes or
 * fourteen without anything being wrong. A tighter threshold would paint the
 * board amber most of the time and teach the reader to ignore it.
 */
export const CADENCE_ALERT_THRESHOLD = 0.35;

/** The board's own accent per chain, so a chain keeps one colour throughout. */
export const CHAIN_TINT: Record<string, string> = {
  bitcoin: 'var(--data-btc)',
  ethereum: '#8a92b2',
  base: '#0052ff',
  arbitrum: '#28a0f0',
  optimism: '#ff0420',
  bsc: '#f0b90b',
  solana: '#14f195',
  tron: '#eb0029',
};

/**
 * The Bitcoin mempool queue, as a phrase.
 *
 * The card's load bar already says how congested the chain is, and it says it
 * the honest way: blocks whose median fee is actually competing, not raw size.
 * This is the other half of that reading — how many transactions are sitting
 * there and how deep the contested part goes — and it is the one on-chain
 * figure the Home board used to carry that nothing on this page did.
 *
 * `null` for both inputs returns null rather than a dash, because only one
 * chain on this board has a mempool at all: eight cards showing "—" would claim
 * seven chains failed to report something they do not have.
 */
export function mempoolQueue(
  txCount: number | null | undefined,
  backlogBlocks: number | null | undefined
): string | null {
  if (typeof txCount !== 'number' && typeof backlogBlocks !== 'number') return null;

  const parts: string[] = [];
  if (typeof txCount === 'number') parts.push(`${formatCount(txCount)} queued`);
  if (typeof backlogBlocks === 'number') {
    // Zero contested blocks is a real and common reading — everything waiting
    // is below the fee floor — and "0 blk deep" states it better than silence.
    parts.push(`${backlogBlocks.toFixed(0)} blk deep`);
  }
  return parts.join(' · ');
}
