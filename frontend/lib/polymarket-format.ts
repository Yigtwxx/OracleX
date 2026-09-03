/**
 * Turning prediction-market numbers into things a reader can act on.
 *
 * The recurring decision in here is what to do with a missing value, and the
 * answer is always the same: show that it is missing. A market priced at 0 is
 * one the crowd says will not happen; a market with no price is one we could not
 * read. Defaulting the second to the first is how a terminal starts publishing
 * confident numbers nobody reported, so every formatter takes `null | undefined`
 * and returns `NO_READING` rather than a zero.
 *
 * Probabilities arrive as a fraction in [0, 1] and are shown as a percentage,
 * because that is how people reason about them. Movements go the other way and
 * stay in points: a market that went from 0.02 to 0.04 doubled, which sounds
 * enormous and means two cents of noise, while 0.45 to 0.62 is seventeen points
 * and is the one worth reading. Percent change would rank the first above the
 * second on every board it appeared on.
 */
import { NO_READING } from '@/lib/chain-format';

export { NO_READING };

/** A probability in [0, 1] as a percentage. `0.625` → `"63%"`. */
export function formatProbability(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_READING;
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * A movement in probability points, signed. `0.17` → `"+17 pts"`.
 *
 * Points rather than percent, deliberately — see the module note. The unit is
 * spelled out because "+17" beside a "63%" invites the reader to take it as
 * percent of the price rather than a shift in the price.
 */
export function formatPoints(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_READING;
  const points = value * 100;
  const rounded = Math.abs(points) < 1 ? points.toFixed(1) : Math.round(points).toString();
  return `${points > 0 ? '+' : ''}${rounded} pts`;
}

/**
 * A market's volume or liquidity, abbreviated.
 *
 * Neither of the existing money formatters fits. `formatUsd` in chain-format is
 * built for sub-cent gas fees and prints a full-precision "$1937854.11" for a
 * figure that only needs three characters of meaning. `formatFlowUsd` does
 * abbreviate, but it signs the number, and a leading "+" on a volume implies a
 * direction that a volume does not have — it is a total, not a flow.
 *
 * Two significant decimals below ten, one above, because "$1.9M" and "$12.1M"
 * carry the same amount of information in the same width, and a column of
 * "$1.94M / $12.14M" is arithmetic nobody is doing.
 */
export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return NO_READING;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(abs >= 1e10 ? 1 : 2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(abs >= 1e7 ? 1 : 2)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

export type Tone = 'up' | 'down' | 'muted';

/** Which way a movement went. Exactly zero is not a direction. */
export function driftTone(value: number | null | undefined): Tone {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) {
    return 'muted';
  }
  return value > 0 ? 'up' : 'down';
}

/**
 * Where a probability sits on a 0–1 track, clamped.
 *
 * Clamped rather than trusted: an outcome price is occasionally quoted a hair
 * outside the range by the upstream, and an unclamped value would push the
 * marker past the end of its bar.
 */
export function oddsFraction(value: number | null | undefined): number | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return Math.min(1, Math.max(0, value));
}

export interface OutcomeLike {
  label: string;
  price?: number | null;
}

/**
 * The outcome the market currently favours.
 *
 * Null when nothing is priced. A market where every price is unknown has no
 * favourite, and picking the first outcome would invent one.
 */
export function leadingOutcome<T extends OutcomeLike>(outcomes: T[]): T | null {
  const priced = outcomes.filter((o) => o.price !== null && o.price !== undefined);
  if (priced.length === 0) return null;
  return priced.reduce((best, o) => ((o.price ?? 0) > (best.price ?? 0) ? o : best));
}

/**
 * How long until a market resolves. `null` once it has, or if we do not know.
 *
 * Returning null for an elapsed deadline rather than a negative countdown: a
 * market past its close is awaiting resolution, and "-3d" beside it would read
 * as a countdown running backwards rather than as a state.
 */
export function timeToClose(endDate: string | null | undefined, nowMs: number): string | null {
  if (!endDate) return null;
  const target = Date.parse(endDate);
  if (Number.isNaN(target)) return null;

  const seconds = Math.floor((target - nowMs) / 1000);
  if (seconds <= 0) return null;

  const days = Math.floor(seconds / 86400);
  if (days >= 1) return `${days}d`;
  const hours = Math.floor(seconds / 3600);
  if (hours >= 1) return `${hours}h`;
  return `${Math.max(1, Math.floor(seconds / 60))}m`;
}

/**
 * How much standing a number has, for the badge beside it.
 *
 * These are not decorative. The map draws three layers that look identical once
 * rendered — a jurisdiction is measured, a market's subject geography is derived
 * from its text, and an activity hour is a real measurement that says very
 * little about location — and the only thing separating them for a reader is
 * this label.
 */
export type Provenance = 'measured' | 'derived' | 'estimated';

export const PROVENANCE_LABEL: Record<Provenance, string> = {
  measured: 'Measured',
  derived: 'Derived',
  estimated: 'Estimated',
};

export const PROVENANCE_DETAIL: Record<Provenance, string> = {
  measured: 'Read directly from a source that published it.',
  derived: 'Computed from measurements by a rule you could re-run.',
  estimated: 'An inference. True of the input, uncertain of the conclusion.',
};

/**
 * Colour per outcome, so a card is read by shape rather than by reading.
 *
 * Two rules, and the first one overrides the second because it carries meaning
 * the palette cannot. **Yes and No are directional**, so they take the semantic
 * up/down pair every other number in this terminal uses for direction — a green
 * "Yes" is the same green as a rising price, and that consistency is worth more
 * than a distinct hue would be.
 *
 * Everything else — team names, candidates, thresholds — is nominal, not
 * directional, and colouring it green or red would assert a good and a bad side
 * of a football match. Those get the neutral chart rotation instead.
 *
 * Assignment is by label so a team keeps its colour from card to card, with
 * collisions inside one market pushed to the next free slot: two outcomes a
 * reader cannot tell apart defeat the point, and within a card distinctness
 * matters more than consistency across cards.
 */
export const OUTCOME_PALETTE = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
];

const YES_WORDS = new Set(['yes', 'up', 'over']);
const NO_WORDS = new Set(['no', 'down', 'under']);

function hashIndex(label: string, modulo: number): number {
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) {
    hash = (hash * 31 + label.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % modulo;
}

/** Label to CSS colour, for every outcome in one market. */
export function outcomeColors(outcomes: OutcomeLike[]): Record<string, string> {
  const colors: Record<string, string> = {};
  const taken = new Set<number>();

  // Directional labels first, so they claim their meaning before the rotation
  // can hand a neutral hue to a "Yes".
  const nominal: string[] = [];
  for (const outcome of outcomes) {
    const word = outcome.label.trim().toLowerCase();
    if (YES_WORDS.has(word)) colors[outcome.label] = 'var(--up)';
    else if (NO_WORDS.has(word)) colors[outcome.label] = 'var(--down)';
    else nominal.push(outcome.label);
  }

  for (const label of nominal) {
    let index = hashIndex(label, OUTCOME_PALETTE.length);
    let attempts = 0;
    while (taken.has(index) && attempts < OUTCOME_PALETTE.length) {
      index = (index + 1) % OUTCOME_PALETTE.length;
      attempts += 1;
    }
    taken.add(index);
    colors[label] = OUTCOME_PALETTE[index];
  }

  return colors;
}

/**
 * Colour per category, for the chip on a card.
 *
 * Deliberately not `--nav-polymarket`: every card wearing the tab's own hue
 * makes the board one colour and the chip decorative. These are picked to sit
 * apart from each other at chip size and away from --up/--down, which the
 * outcome rows are already using for direction.
 */
export const CATEGORY_TINT: Record<string, string> = {
  politics: '#5b8def',
  geopolitics: '#f0883e',
  macro: '#7ddfe8',
  crypto: '#eab04a',
  sports: '#a3d95c',
  general: '#9a9aa3',
};

export function categoryTint(key: string): string {
  return CATEGORY_TINT[key] ?? CATEGORY_TINT.general;
}

export const CATEGORY_LABEL: Record<string, string> = {
  politics: 'Politics',
  geopolitics: 'Geopolitics',
  macro: 'Macro',
  crypto: 'Crypto',
  sports: 'Sports',
  general: 'General',
};

export function categoryLabel(key: string): string {
  return CATEGORY_LABEL[key] ?? 'General';
}
