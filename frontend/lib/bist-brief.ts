/**
 * The three BIST instruments a reader follows, and where they live between
 * visits.
 *
 * The crypto board's equivalent (`lib/asset-brief.ts`) stores bare symbols,
 * because everything it can hold resolves through one endpoint. This realm has
 * two populations that do not share an identifier space — a listed company and
 * a TEFAS fund are both three-to-five uppercase characters, and `TI7` is a fund
 * while `TTRAK` is a share — so a slot carries which board it came from rather
 * than leaving the card to guess and fetch twice.
 *
 * Pure on purpose: the vitest suite collects `lib/**` only, and a slot list that
 * silently drops an entry is exactly the failure that renders perfectly.
 */

import type { ViopContract } from '@/lib/bist-api';
import { turkishFold } from '@/lib/bist-format';

export type BistBriefKind = 'stock' | 'fund';

export interface BistBriefSlot {
  kind: BistBriefKind;
  /** Ticker for a share, TEFAS code for a fund. Always normalised. */
  code: string;
}

/** Where the chosen instruments live between visits. */
export const BIST_BRIEF_STORAGE_KEY = 'oraclex.bist.brief';

/** Three cards is what fits at `lg` without any one of them becoming unreadable. */
export const MAX_BIST_BRIEF = 3;

/**
 * What the strip shows before anyone has chosen anything.
 *
 * Two shares and one fund, and the fund is the load-bearing one: it is what
 * tells a first visitor that this board is not an equities screener, and an
 * empty third slot would not. The same reasoning put an equity in the crypto
 * board's third slot.
 */
export const DEFAULT_BIST_BRIEF: readonly BistBriefSlot[] = [
  { kind: 'stock', code: 'THYAO' },
  { kind: 'stock', code: 'ASELS' },
  { kind: 'fund', code: 'TI7' },
];

interface StoredBrief {
  v: 1;
  slots: BistBriefSlot[];
}

/**
 * Uppercase, ASCII, punctuation stripped.
 *
 * The dotted/dotless pair is the reason this is not a bare `toUpperCase()`.
 * Borsa İstanbul writes every ticker in ASCII — `ISCTR`, not `İŞCTR` — but a
 * Turkish keyboard produces `ı` and `İ`, and `'ı'.toUpperCase()` gives `I`
 * while `'i'.toUpperCase()` gives `I` only outside a Turkish locale. Mapping
 * both to ASCII `I` first makes the result the same whatever locale the browser
 * is in, which is what keeps `isctr` and `ısctr` from becoming two slots.
 */
export function normalizeCode(raw: string): string {
  return raw
    .trim()
    .replace(/[İIıi]/g, 'I')
    .replace(/[^0-9A-Za-z]/g, '')
    .toUpperCase();
}

/** Stable identity for a slot — a fund and a share may share a code. */
export function slotKey(slot: BistBriefSlot): string {
  return `${slot.kind}:${slot.code}`;
}

function isKind(value: unknown): value is BistBriefKind {
  return value === 'stock' || value === 'fund';
}

/**
 * Clean a candidate slot list: normalised, de-duplicated, capped.
 *
 * Returns null when nothing usable survives, so the caller can fall back rather
 * than render an empty strip.
 */
export function sanitizeSlots(input: unknown): BistBriefSlot[] | null {
  if (!Array.isArray(input)) return null;

  const seen = new Set<string>();
  const out: BistBriefSlot[] = [];
  for (const entry of input) {
    if (!entry || typeof entry !== 'object') continue;
    const candidate = entry as Partial<BistBriefSlot>;
    if (!isKind(candidate.kind) || typeof candidate.code !== 'string') continue;
    const code = normalizeCode(candidate.code);
    if (!code) continue;
    const key = `${candidate.kind}:${code}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ kind: candidate.kind, code });
    if (out.length === MAX_BIST_BRIEF) break;
  }
  return out.length ? out : null;
}

function safeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * The stored slot list, or the default.
 *
 * Never throws and never returns an empty list. Storage disabled, a value from
 * an older version, hand-edited JSON — all of them land on the default rather
 * than on a blank board.
 */
export function readBistBrief(storage?: Storage): BistBriefSlot[] {
  const store = storage ?? safeStorage();
  if (!store) return [...DEFAULT_BIST_BRIEF];

  try {
    const raw = store.getItem(BIST_BRIEF_STORAGE_KEY);
    if (!raw) return [...DEFAULT_BIST_BRIEF];
    const parsed = JSON.parse(raw) as Partial<StoredBrief>;
    // A well-formed payload is authoritative, including when its list is empty.
    // Routing an empty array through the `?? DEFAULT` fallback would put THYAO
    // back on the board of every reader who had deliberately cleared it — the
    // fallback is for storage that cannot be read, not for an answer of "none".
    if (!Array.isArray(parsed?.slots)) return [...DEFAULT_BIST_BRIEF];
    return sanitizeSlots(parsed.slots) ?? [];
  } catch {
    return [...DEFAULT_BIST_BRIEF];
  }
}

/**
 * Persist the slot list.
 *
 * An empty list is written as an empty list rather than refused: a reader who
 * removed all three slots means it, and falling back to the default here would
 * put THYAO back on their board every time they reloaded.
 */
export function writeBistBrief(slots: BistBriefSlot[], storage?: Storage): void {
  const store = storage ?? safeStorage();
  if (!store) return;
  try {
    store.setItem(
      BIST_BRIEF_STORAGE_KEY,
      JSON.stringify({ v: 1, slots: sanitizeSlots(slots) ?? [] } satisfies StoredBrief)
    );
  } catch {
    // Private mode, quota, a browser blocking site data. The board still works.
  }
}

/**
 * Put `slot` in position `index`, or drop the position when `slot` is null.
 *
 * An instrument already sitting in another position swaps with the target
 * rather than appearing twice — putting THYAO in slot 3 when it is already
 * slot 1 should leave three instruments on the board, not two and a duplicate.
 */
export function setBistSlot(
  current: BistBriefSlot[],
  index: number,
  slot: BistBriefSlot | null
): BistBriefSlot[] {
  const next = [...current];

  if (slot === null) {
    next.splice(index, 1);
    return sanitizeSlots(next) ?? [];
  }

  const code = normalizeCode(slot.code);
  if (!code) return current;
  const clean: BistBriefSlot = { kind: slot.kind, code };

  const existing = next.findIndex((entry) => slotKey(entry) === slotKey(clean));
  if (existing !== -1 && existing !== index) {
    next[existing] = next[index] ?? clean;
  }
  next[index] = clean;

  return sanitizeSlots(next) ?? current;
}

/** Append when there is room, otherwise leave the list untouched. */
export function addBistSlot(current: BistBriefSlot[], slot: BistBriefSlot): BistBriefSlot[] {
  const code = normalizeCode(slot.code);
  if (!code || current.length >= MAX_BIST_BRIEF) return current;
  const clean: BistBriefSlot = { kind: slot.kind, code };
  if (current.some((entry) => slotKey(entry) === slotKey(clean))) return current;
  return sanitizeSlots([...current, clean]) ?? current;
}

// ── Choosing one ─────────────────────────────────────────────────────────────

/** A candidate for a slot, from either board. */
export interface BistInstrument {
  kind: BistBriefKind;
  code: string;
  name: string;
  /** Sector for a share, umbrella type for a fund — what tells two apart. */
  note?: string;
}

/**
 * Rank instruments against what the reader typed.
 *
 * `turkishFold` rather than `toLowerCase`, and that is not pedantry: on this
 * board `'KESİCİ'.toLowerCase()` leaves a combining dot behind, so a search for
 * a company name typed in capitals silently misses it. The backend folds the
 * same way (`services/bist/text.py`), and the two have to agree or the same
 * query answers differently on either side.
 *
 * The ranking exists because a bare substring match buries the answer: typing
 * `IS` matches `ISCTR` and also every fund with "İŞ" in its title, and the
 * ticker is what the reader meant. Exact code first, then code prefix, then the
 * name.
 */
export function searchInstruments(
  options: readonly BistInstrument[],
  query: string,
  limit = 12
): BistInstrument[] {
  const needle = turkishFold(query.trim());
  if (!needle) return options.slice(0, limit);

  const scored: { option: BistInstrument; rank: number; index: number }[] = [];

  options.forEach((option, index) => {
    const code = turkishFold(option.code);
    const name = turkishFold(option.name);

    let rank: number | null = null;
    if (code === needle) rank = 0;
    else if (code.startsWith(needle)) rank = 1;
    else if (name.startsWith(needle)) rank = 2;
    else if (name.includes(needle)) rank = 3;
    else if (code.includes(needle)) rank = 4;

    if (rank !== null) scored.push({ option, rank, index });
  });

  // Original order breaks ties, so a board already sorted by capitalisation or
  // by return keeps that order inside each rank.
  scored.sort((a, b) => a.rank - b.rank || a.index - b.index);
  return scored.slice(0, limit).map((entry) => entry.option);
}

// ── Readings the cards draw ──────────────────────────────────────────────────

export type BistTone = 'up' | 'down' | 'neutral';

/** Tailwind text colour for a tone. Literal classes — Tailwind cannot see built ones. */
export const BIST_TONE_TEXT: Record<BistTone, string> = {
  up: 'text-up',
  down: 'text-down',
  neutral: 'text-fg-muted',
};

export interface Band {
  label: string;
  tone: BistTone;
}

/**
 * RSI as a Turkish word, on the bands the rest of the app already uses.
 *
 * Returned rather than computed in JSX so the thresholds live in one testable
 * place: a wrong label here ("aşırı satım" on an RSI of 79) renders perfectly
 * and reads as a fact.
 *
 * The tone is the *trade* reading, not the direction of the number: an
 * overbought reading is a warning, so it is red even though the price rose to
 * get there. That is the same inversion `lib/asset-brief.ts` makes.
 */
export function rsiBand(rsi: number | null): Band | null {
  if (rsi === null || !Number.isFinite(rsi)) return null;
  if (rsi >= 70) return { label: 'aşırı alım', tone: 'down' };
  if (rsi <= 30) return { label: 'aşırı satım', tone: 'up' };
  if (rsi >= 55) return { label: 'güçlü', tone: 'up' };
  if (rsi <= 45) return { label: 'zayıf', tone: 'down' };
  return { label: 'nötr', tone: 'neutral' };
}

/**
 * Today's turnover against its own average, as a word.
 *
 * The bands are wide because daily volume is noisy: a 1.2× session is an
 * ordinary session, and calling it "yoğun" would badge the card roughly half
 * the time, which is the same as not badging it at all.
 */
export function volumeBand(ratio: number | null): Band | null {
  if (ratio === null || !Number.isFinite(ratio) || ratio <= 0) return null;
  if (ratio >= 2) return { label: 'ağır', tone: 'up' };
  if (ratio >= 1.4) return { label: 'yoğun', tone: 'up' };
  if (ratio <= 0.6) return { label: 'ince', tone: 'down' };
  return { label: 'normal', tone: 'neutral' };
}

/**
 * Where in its own year a share is trading, as a word.
 *
 * `range_position` is published by the API on the positioning board and derived
 * here from the 52-week bounds for a card that has them. The middle band is
 * deliberately wide — most shares spend most of the year in it, and a label
 * that fires everywhere says nothing.
 */
export function rangeBand(position: number | null): Band | null {
  if (position === null || !Number.isFinite(position)) return null;
  if (position >= 0.9) return { label: 'zirveye yakın', tone: 'up' };
  if (position <= 0.1) return { label: 'dibe yakın', tone: 'down' };
  if (position >= 0.66) return { label: 'aralığın üstü', tone: 'up' };
  if (position <= 0.33) return { label: 'aralığın altı', tone: 'down' };
  return { label: 'aralığın ortası', tone: 'neutral' };
}

/**
 * A fund's Sharpe, as a word.
 *
 * Negative Sharpe is the case worth naming: it means the fund returned less
 * than the risk-free rate while taking risk to do it, which the return column
 * cannot show. The thresholds are conventional rather than derived, so the
 * label says "birim riske düşen getiri" beside it wherever it is shown.
 */
export function sharpeBand(sharpe: number | null): Band | null {
  if (sharpe === null || !Number.isFinite(sharpe)) return null;
  if (sharpe < 0) return { label: 'risksiz getirinin altında', tone: 'down' };
  if (sharpe >= 1) return { label: 'güçlü', tone: 'up' };
  if (sharpe >= 0.5) return { label: 'makul', tone: 'neutral' };
  return { label: 'zayıf', tone: 'down' };
}

/**
 * Where a price sits between two bounds, 0–1.
 *
 * Null unless both bounds exist and bracket the price: a bar drawn from one
 * bound and a guess would be a picture of a measurement that was not taken.
 */
export function bandPosition(
  price: number | null,
  low: number | null,
  high: number | null
): number | null {
  if (price === null || low === null || high === null) return null;
  if (!Number.isFinite(price) || !Number.isFinite(low) || !Number.isFinite(high)) return null;
  if (!(high > low) || price < low || price > high) return null;
  return (price - low) / (high - low);
}

// ── Futures ──────────────────────────────────────────────────────────────────

/**
 * The one VİOP contract worth putting on a card, for a given underlying.
 *
 * Borsa İstanbul lists several expiries per underlying and a card has room for
 * one. The pick is the largest open interest rather than the nearest expiry,
 * and that is a deliberate substitution: the expiry arrives as a Turkish date
 * string (`"30 Eyl 26"`), parsing it would be a second date parser to keep in
 * step with the exchange's own abbreviations, and the front month is the one
 * carrying the position anyway. The label on the card names what was picked —
 * open interest — so the reader is never shown a "front month" that was
 * inferred.
 *
 * Most shares have no listed contract at all: the board is a few dozen rows
 * across a handful of underlyings. Null is the ordinary answer, and the card
 * says so rather than leaving a gap that reads as a missing figure.
 */
export function pickViopContract(
  contracts: readonly ViopContract[] | undefined,
  underlying: string
): ViopContract | null {
  if (!contracts?.length) return null;
  const wanted = normalizeCode(underlying);
  if (!wanted) return null;

  let best: ViopContract | null = null;
  for (const contract of contracts) {
    if (normalizeCode(contract.underlying ?? '') !== wanted) continue;
    const open = contract.open_interest ?? 0;
    const bestOpen = best?.open_interest ?? -1;
    if (!best || open > bestOpen) best = contract;
  }
  return best;
}
