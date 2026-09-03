/**
 * Turkish formatting for the Borsa İstanbul surface.
 *
 * The first locale-aware layer in this codebase. Everything else hardcodes
 * `'en-US'` or `'en-GB'`, which is right for a board of US equities and wrong
 * for one where the reader expects `1.234,56 ₺` and `%12,3`.
 *
 * Three conventions here are not cosmetic and will read as bugs if reversed:
 *
 * **The percent sign comes first.** Turkish writes `%12,3`, not `12,3%`. Every
 * Turkish finance site, every KAP filing and every TEFAS page does this.
 *
 * **The separators are swapped.** `.` groups thousands and `,` is the decimal
 * point, so `1.234,56` is one thousand two hundred — a figure an English-reading
 * parser would take as `1.23`.
 *
 * **Missing is not zero.** `EMPTY` is what a null renders as. The commonest
 * null on this surface is a real return that could not be computed because the
 * inflation series for that window is unavailable, and showing `%0,0` there
 * would state the opposite of what is known.
 */

/**
 * The single no-data sentinel for this realm.
 *
 * The codebase is inconsistent — `'--'` on the overview board, `'—'` in the
 * chain and technical modules, `'Unknown'` in ownership. BIST picks the em dash
 * and uses it everywhere, because the cell a reader will meet most often is an
 * uncomputable real return and that has to look unmistakably different from a
 * measured zero.
 */
export const EMPTY = '—';

const LOCALE = 'tr-TR';

/**
 * The space between a figure and its unit.
 *
 * Non-breaking, so `304,50 ₺` never wraps across a table cell with the symbol
 * orphaned on the next line. Named rather than typed inline because U+00A0 is
 * invisible in a diff and in a test expectation — the first version of this
 * file used a literal one and the test that asserted a plain space failed with
 * two strings that looked identical in the output.
 */
export const NBSP = '\u00a0';

/** Borsa İstanbul's continuous auction, in minutes past midnight, Istanbul time. */
export const SESSION_OPEN_MINUTES = 10 * 60;
export const SESSION_CLOSE_MINUTES = 18 * 60;

/** Every BIST quote in this app is at least this far behind the exchange. */
export const DELAY_MINUTES = 15;

function isNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

// ── Numbers ────────────────────────────────────────────────────────────────

export function formatNumber(value: number | null | undefined, decimals: number = 2): string {
  if (!isNumber(value)) return EMPTY;
  return value.toLocaleString(LOCALE, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * A price in lira.
 *
 * The symbol trails the number with a non-breaking space, which is the Turkish
 * convention and also what keeps `304,50 ₺` from wrapping across a table cell.
 */
export function formatTry(value: number | null | undefined, decimals: number = 2): string {
  if (!isNumber(value)) return EMPTY;
  return `${formatNumber(value, decimals)}${NBSP}₺`;
}

/**
 * Compact magnitude, in Turkish.
 *
 * `bin`/`mn`/`mr`/`tn` rather than `K`/`M`/`B`/`T`: the English `B` means
 * *billion*, the Turkish `milyar` starts with the same letter, and a reader who
 * takes one for the other is off by a factor of a thousand. Turkish
 * abbreviations remove the ambiguity entirely.
 */
export function formatCompact(value: number | null | undefined, decimals: number = 1): string {
  if (!isNumber(value)) return EMPTY;
  const sign = value < 0 ? '-' : '';
  const magnitude = Math.abs(value);

  const tiers: [number, string][] = [
    [1e12, 'tn'],
    [1e9, 'mr'],
    [1e6, 'mn'],
    [1e3, 'bin'],
  ];
  for (const [threshold, suffix] of tiers) {
    if (magnitude >= threshold) {
      return `${sign}${formatNumber(magnitude / threshold, decimals)}${NBSP}${suffix}`;
    }
  }
  return `${sign}${formatNumber(magnitude, 0)}`;
}

/** Compact lira — what a market capitalisation column shows. */
export function formatCompactTry(value: number | null | undefined): string {
  if (!isNumber(value)) return EMPTY;
  return `${formatCompact(value)}${NBSP}₺`;
}

// ── Percentages ────────────────────────────────────────────────────────────

/**
 * A fraction as a Turkish percentage: `0.1234` → `%12,3`.
 *
 * Input is always a fraction, never an already-multiplied percentage. Every
 * `/api/bist/*` payload converts at the boundary for exactly this reason, so a
 * value arriving here as `12.34` means twelve hundred percent and is a bug
 * upstream rather than something to guess about.
 */
export function formatPercent(value: number | null | undefined, decimals: number = 1): string {
  if (!isNumber(value)) return EMPTY;
  return `%${formatNumber(value * 100, decimals)}`;
}

/** Same, with an explicit `+` on gains — for change columns. */
export function formatSignedPercent(
  value: number | null | undefined,
  decimals: number = 1
): string {
  if (!isNumber(value)) return EMPTY;
  const sign = value > 0 ? '+' : '';
  return `${sign}${formatPercent(value, decimals)}`;
}

/**
 * Borsa İstanbul's daily price limit.
 *
 * Most shares may move at most ten percent in either direction in a session.
 * The limit is why the next function can say something a US board could not.
 */
export const DAILY_LIMIT = 0.1;

/**
 * Whether a reported day change is too large to have been trading.
 *
 * SDT Uzay ve Savunma showed `-%90,4` on the board the day this was written.
 * The company did not lose ninety percent of its value; it did a roughly
 * ten-for-one bonus issue and the quote source reports the unadjusted gap as an
 * ordinary price change. A reader scanning a losers list would take it for a
 * collapse.
 *
 * A daily limit makes this detectable in a way it would not be on an unbounded
 * market: a move past the limit did not happen through trading, so it is a
 * capital action — a bonus issue, a split, a rights adjustment. This does not
 * claim to know *which*, only that the figure is not a price move, which is
 * enough to stop it being read as one.
 *
 * Deliberately generous at 1.5×: the limit is widened for some markets and for
 * newly listed shares, and a false positive here costs a footnote while a false
 * negative costs the reader a wrong conclusion.
 */
export function isLikelyCapitalAction(change: number | null | undefined): boolean {
  return isNumber(change) && Math.abs(change) > DAILY_LIMIT * 1.5;
}

export const CAPITAL_ACTION_NOTE =
  'Günlük fiyat limitinin dışında — büyük olasılıkla bedelsiz, bölünme veya sermaye işlemi. Fiyat düşüşü değil.';

/** Tailwind text colour for a signed figure. Zero and unknown stay neutral. */
export function toneClass(value: number | null | undefined): string {
  if (!isNumber(value) || value === 0) return 'text-fg-muted';
  return value > 0 ? 'text-up' : 'text-down';
}

// ── Framed returns ─────────────────────────────────────────────────────────

/** The shape every return on this surface arrives in. Mirrors the API. */
export interface FramedReturn {
  nominal: number;
  real: number | null;
  usd: number | null;
}

/**
 * Why a real return is missing, in the words the tooltip will show.
 *
 * Never "0%" and never blank: the reader has to be able to tell "we could not
 * compute this" from "this window returned nothing", and those are the two
 * readings a bare empty cell collapses together.
 */
export function realReturnNote(framed: FramedReturn | null | undefined): string {
  if (!framed) return 'Veri yok.';
  if (framed.real !== null) return 'Enflasyona göre düzeltilmiş getiri.';
  return 'Bu dönem için enflasyon serisi yok, reel getiri hesaplanamadı.';
}

/**
 * Whether the nominal figure flatters the real one enough to be worth flagging.
 *
 * A gain in lira that is a loss after inflation is the single fact this realm
 * exists to surface, so it gets its own predicate rather than being re-derived
 * at each call site.
 */
export function isRealLoss(framed: FramedReturn | null | undefined): boolean {
  return !!framed && framed.nominal > 0 && framed.real !== null && framed.real < 0;
}

// ── Dates and times ────────────────────────────────────────────────────────

const MONTHS_SHORT = [
  'Oca',
  'Şub',
  'Mar',
  'Nis',
  'May',
  'Haz',
  'Tem',
  'Ağu',
  'Eyl',
  'Eki',
  'Kas',
  'Ara',
];

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** `2026-08-27` → `27 Ağu 2026`. */
export function formatDate(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return EMPTY;
  return `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]} ${date.getFullYear()}`;
}

/** `2026-08-27T15:06:10` → `27 Ağu 2026 15:06`. */
export function formatDateTime(value: string | null | undefined): string {
  const date = parse(value);
  if (!date) return EMPTY;
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${formatDate(value)} ${hours}:${minutes}`;
}

/**
 * How long ago, in Turkish.
 *
 * `now` is injectable so the thresholds can be tested without freezing the
 * clock — the same reason the calendar builder on the backend takes a `today`.
 */
export function formatRelative(value: string | null | undefined, now: Date = new Date()): string {
  const date = parse(value);
  if (!date) return EMPTY;
  const seconds = Math.max(0, (now.getTime() - date.getTime()) / 1000);
  if (seconds < 60) return 'az önce';
  if (seconds < 3600) return `${Math.round(seconds / 60)} dk önce`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} sa önce`;
  return `${Math.round(seconds / 86400)} gün önce`;
}

// ── Session ────────────────────────────────────────────────────────────────

export type SessionState = 'pre' | 'open' | 'closed' | 'weekend';

/**
 * Where the trading day is right now, in Istanbul.
 *
 * Computed against Istanbul rather than the reader's own clock: a user in
 * Berlin asking whether the market is open means Borsa İstanbul's hours, not
 * theirs. The offset comes from `Intl` rather than a hardcoded +03:00 so the
 * answer stays right if Turkey ever reintroduces daylight saving.
 */
export function sessionState(now: Date = new Date()): SessionState {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Istanbul',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(now);

  const lookup = (type: string) => parts.find((part) => part.type === type)?.value ?? '';
  const weekday = lookup('weekday');
  if (weekday === 'Sat' || weekday === 'Sun') return 'weekend';

  const minutes = Number(lookup('hour')) * 60 + Number(lookup('minute'));
  if (minutes < SESSION_OPEN_MINUTES) return 'pre';
  if (minutes >= SESSION_CLOSE_MINUTES) return 'closed';
  return 'open';
}

export const SESSION_LABEL: Record<SessionState, string> = {
  pre: 'Seans öncesi',
  open: 'Seans açık',
  closed: 'Seans kapalı',
  weekend: 'Hafta sonu',
};

// ── Search ─────────────────────────────────────────────────────────────────

/**
 * Turkish-aware lowercase, mirroring `services/bist/text.py` on the backend.
 *
 * `'KESİCİ'.toLowerCase()` leaves a combining dot behind — an ASCII `i` plus
 * U+0307 — while `'Kesici'.toLowerCase()` gives a plain `i`, so the two do not
 * compare equal and a search for a company name in capitals silently misses.
 * Mapping the dotted capital to `i` and the dotless to `ı` first is the Turkish
 * rule; the backend hit exactly this and the frontend has to agree with it or
 * the same query returns different results on either side.
 */
export function turkishFold(text: string): string {
  return text.replace(/İ/g, 'i').replace(/I/g, 'ı').toLowerCase();
}

/** Case-insensitive substring test that survives Turkish capitals. */
export function turkishIncludes(haystack: string, needle: string): boolean {
  return turkishFold(haystack).includes(turkishFold(needle));
}
