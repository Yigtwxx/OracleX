/**
 * Derivations for the elections board.
 *
 * Everything here is UTC-anchored, and that is not fussiness. An election is an
 * all-day event in its own country's time; if the server drops a row at UTC
 * midnight while the client counts down in local time, the same election reads
 * as one day nearer for a reader in Auckland than for one in Los Angeles, and
 * disappears a day early for one of them. Both sides measure from UTC midnight
 * so the countdown means the same thing everywhere.
 *
 * These live in `lib/` rather than beside the panel because vitest only
 * collects `lib/**\/*.test.ts` — a helper defined inside a component is a helper
 * nobody can test.
 */

/** A price Polymarket is quoting, not a probability — see `oddsState`. */
export interface ElectionOutcome {
  label: string;
  price: number;
  change_1w: number | null;
}

export interface ElectionMarketLink {
  event_slug: string;
  event_title: string;
  url: string;
  confidence: 'high' | 'medium';
  matched_on: string[];
}

export interface ElectionOdds extends ElectionMarketLink {
  volume_24h: number;
  liquidity: number;
  /** Gamma's own statement that the outcomes are mutually exclusive. */
  exclusive: boolean;
  outcomes: ElectionOutcome[];
  /** Outcomes beyond the ones listed, counted rather than dropped silently. */
  others: number;
}

export interface Election {
  id: string;
  date: string;
  through: string | null;
  /** 'month' when the article names a month but no day. */
  precision: 'day' | 'month';
  country: string;
  iso2: string | null;
  flag: string;
  office: string;
  /** A dependent territory or a state with limited recognition. */
  minor: boolean;
  tier: 'major' | 'watch' | null;
  tickers: string[];
  note: string | null;
  odds: ElectionOdds | null;
  market_link: ElectionMarketLink | null;
  source_url: string;
}

export interface ElectionsBoard {
  elections: Election[];
  odds_available: boolean;
  odds_cap: number;
  years: number[];
  as_of: string;
  stale: boolean;
}

export type TierFilter = 'tracked' | 'all';

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole days from today to `dateIso`, both measured at UTC midnight. */
export function daysUntil(dateIso: string, nowMs: number): number | undefined {
  const target = Date.parse(`${dateIso}T00:00:00Z`);
  if (Number.isNaN(target)) return undefined;
  const now = new Date(nowMs);
  const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((target - todayUtc) / DAY_MS);
}

/**
 * The countdown a reader would say out loud.
 *
 * Returns undefined for a month-precision row rather than a number: counting
 * down to the first of a month asserts a polling day nobody has announced.
 */
export function formatCountdown(days: number | undefined): string {
  if (days === undefined) return '–';
  if (days <= 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days < 21) return `${days}d`;
  if (days < 60) return `${Math.round(days / 7)}w`;
  return `${Math.round(days / 30)}mo`;
}

/** How close a row is, for the emphasis the panel gives it. */
export function urgencyTier(days: number | undefined): 'imminent' | 'near' | 'scheduled' {
  if (days === undefined) return 'scheduled';
  if (days <= 14) return 'imminent';
  if (days <= 60) return 'near';
  return 'scheduled';
}

/** "Sep 13" for a day, "September" for a month with no announced day. */
export function formatWhen(row: Election): string {
  const parsed = new Date(`${row.date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return row.date;
  const month = MONTHS[parsed.getUTCMonth()].slice(0, 3);
  if (row.precision === 'month') return month;
  const day = parsed.getUTCDate();
  if (!row.through) return `${month} ${day}`;
  const end = new Date(`${row.through}T00:00:00Z`);
  return Number.isNaN(end.getTime()) ? `${month} ${day}` : `${month} ${day}–${end.getUTCDate()}`;
}

export interface MonthGroup {
  label: string;
  rows: Election[];
}

/**
 * Rows under a month heading, in calendar order across the year boundary.
 *
 * The label is built from a literal month array rather than `toLocaleString`:
 * a heading that reads "Eylül" on one machine and "September" on another would
 * make the assertion in the test a claim about the runner's locale.
 */
export function groupByMonth(rows: Election[]): MonthGroup[] {
  const groups: MonthGroup[] = [];
  for (const row of rows) {
    const parsed = new Date(`${row.date}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime())) continue;
    const label = `${MONTHS[parsed.getUTCMonth()]} ${parsed.getUTCFullYear()}`;
    const last = groups[groups.length - 1];
    if (last?.label === label) last.rows.push(row);
    else groups.push({ label, rows: [row] });
  }
  return groups;
}

/**
 * The board a filter leaves behind.
 *
 * 'tracked' hides the countries the registry has no market view on, along with
 * the dependent territories. That is the default because a desk scanning for a
 * catalyst is not repositioning for the Isle of Man — but it is a filter, not a
 * truncation, and the full list is one click away.
 */
export function applyTierFilter(rows: Election[], filter: TierFilter): Election[] {
  if (filter === 'all') return rows;
  return rows.filter((row) => row.tier !== null && !row.minor);
}

/**
 * What a row can honestly show in its market column.
 *
 * Three states that must never collapse into each other: a price we stand
 * behind, a market we can point at but not price, and no match at all. The
 * backend already decided which; this is the single place the frontend reads
 * that decision, so a component cannot accidentally render a link as a price.
 */
export function oddsState(row: Election): 'priced' | 'linked' | 'unmatched' {
  if (row.odds) return 'priced';
  if (row.market_link) return 'linked';
  return 'unmatched';
}

/** The outcome trading highest, or undefined when there is nothing to lead with. */
export function leadOutcome(odds: ElectionOdds | null): ElectionOutcome | undefined {
  return odds?.outcomes?.[0];
}

/**
 * The gap between the first and second outcome — the "is this a race?" number.
 *
 * undefined rather than 0 when there is only one priced outcome: an unopposed
 * market and a dead heat are opposite readings and must not share a value.
 */
export function oddsSpread(odds: ElectionOdds | null): number | undefined {
  const outcomes = odds?.outcomes ?? [];
  if (outcomes.length < 2) return undefined;
  return outcomes[0].price - outcomes[1].price;
}

/** "62%" — a market price, never rounded to a certainty it is not quoting. */
export function formatPrice(price: number): string {
  const pct = price * 100;
  if (pct >= 99.5 && pct < 100) return '>99%';
  if (pct > 0 && pct <= 0.5) return '<1%';
  return `${Math.round(pct)}%`;
}

/**
 * A week's move in percentage points, or undefined when there is no reading.
 *
 * A change of exactly zero is a reading — the market did not move — and renders
 * as such rather than as the dash that means "we do not know".
 */
export function formatMomentum(change: number | null): string | undefined {
  if (change === null || Number.isNaN(change)) return undefined;
  const points = change * 100;
  if (Math.abs(points) < 0.5) return '0';
  return `${points > 0 ? '+' : '−'}${Math.abs(Math.round(points))}`;
}

/** What the board actually reaches, read off the rows rather than asserted. */
export function horizonNote(rows: Election[], cap: number, oddsAvailable: boolean): string {
  const odds = oddsAvailable
    ? `Odds cover the ${cap} most-traded election markets.`
    : 'Odds unavailable — dates only.';
  if (rows.length === 0) return odds;
  const last = rows[rows.length - 1];
  const parsed = new Date(`${last.date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return odds;
  return `Through ${MONTHS[parsed.getUTCMonth()]} ${parsed.getUTCFullYear()}. ${odds}`;
}
