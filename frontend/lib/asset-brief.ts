import type { AssetBrief } from '@/lib/api';

/**
 * The Home brief's slot list, and the readings the cards derive from a payload.
 *
 * Everything here is pure so the vitest suite can hold it. The components below
 * `components/home/AssetBrief*.tsx` render what this file returns and decide
 * nothing themselves — which matters because a wrong label here ("oversold" on
 * an RSI of 70) is the kind of failure that renders perfectly and reads as a
 * fact.
 */

/** Where the chosen symbols live between visits. */
export const BRIEF_STORAGE_KEY = 'oraclex.brief.symbols';

/**
 * What the strip shows before anyone has chosen anything.
 *
 * Two majors and one equity on purpose: the third slot is what tells a first
 * visitor the board is not crypto-only, and an empty third slot would not.
 */
export const DEFAULT_BRIEF_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'NVDA'];

/** Three cards is what fits at `lg` without either one becoming unreadable. */
export const MAX_BRIEF_SYMBOLS = 3;

interface StoredBrief {
  v: 1;
  symbols: string[];
}

/**
 * Uppercase, trimmed, `$` stripped.
 *
 * The `$` is not cosmetic: people paste `$NVDA` out of habit from social feeds,
 * and the backend's resolver strips it too — normalising here keeps the slot
 * list from holding two entries that are the same asset.
 */
export function normalizeSymbol(raw: string): string {
  return raw.trim().replace(/^\$+/, '').toUpperCase();
}

/**
 * Clean a candidate slot list: normalised, de-duplicated, capped, non-empty.
 *
 * Returns null when nothing usable survives, so the caller can fall back rather
 * than render an empty strip.
 */
export function sanitizeSymbols(input: unknown): string[] | null {
  if (!Array.isArray(input)) return null;

  const seen = new Set<string>();
  const out: string[] = [];
  for (const entry of input) {
    if (typeof entry !== 'string') continue;
    const symbol = normalizeSymbol(entry);
    if (!symbol || seen.has(symbol)) continue;
    seen.add(symbol);
    out.push(symbol);
    if (out.length === MAX_BRIEF_SYMBOLS) break;
  }
  return out.length ? out : null;
}

/**
 * The stored slot list, or the default.
 *
 * Never throws and never returns an empty list. A browser with storage disabled,
 * a value written by an older version, hand-edited JSON — all of them land on
 * the default rather than on a blank board.
 */
export function readBriefSymbols(storage?: Storage): string[] {
  const store = storage ?? safeStorage();
  if (!store) return DEFAULT_BRIEF_SYMBOLS;

  try {
    const raw = store.getItem(BRIEF_STORAGE_KEY);
    if (!raw) return DEFAULT_BRIEF_SYMBOLS;
    const parsed = JSON.parse(raw) as Partial<StoredBrief>;
    return sanitizeSymbols(parsed?.symbols) ?? DEFAULT_BRIEF_SYMBOLS;
  } catch {
    return DEFAULT_BRIEF_SYMBOLS;
  }
}

/** Persist the slot list. A storage failure is not worth surfacing to anyone. */
export function writeBriefSymbols(symbols: string[], storage?: Storage): void {
  const store = storage ?? safeStorage();
  if (!store) return;
  const clean = sanitizeSymbols(symbols);
  if (!clean) return;
  try {
    store.setItem(
      BRIEF_STORAGE_KEY,
      JSON.stringify({ v: 1, symbols: clean } satisfies StoredBrief)
    );
  } catch {
    // Private mode, quota, a browser blocking site data. The board still works.
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Put `symbol` in slot `index`, or drop the slot when `symbol` is null.
 *
 * A symbol already sitting in another slot swaps with the target rather than
 * appearing twice — dragging BTC onto slot 3 when it is already slot 1 should
 * leave three assets on the board, not two and a duplicate.
 */
export function setSlot(current: string[], index: number, symbol: string | null): string[] {
  const next = [...current];

  if (symbol === null) {
    next.splice(index, 1);
    return sanitizeSymbols(next) ?? [];
  }

  const clean = normalizeSymbol(symbol);
  if (!clean) return current;

  const existing = next.indexOf(clean);
  if (existing !== -1 && existing !== index) {
    next[existing] = next[index] ?? clean;
  }
  next[index] = clean;

  return sanitizeSymbols(next) ?? current;
}

/**
 * Quote currencies a pair can end in, longest first.
 *
 * Order is load-bearing: `USD` before `USDT` would turn `BTCUSDT` into `BTCT`.
 */
const QUOTE_SUFFIXES = ['USDT', 'USDC', 'FDUSD', 'BUSD', 'TUSD', 'USD'];

/**
 * The asset behind a pair: `BINANCE:BTCUSDT` → `BTC`, `NVDA` → `NVDA`.
 *
 * Logo URLs are built from the asset, not the pair — `btcusdt-btcusdt-logo.png`
 * is a 404 on every logo host there is. Equities pass through untouched, which
 * is why the suffix has to be longer than nothing left over: a hypothetical
 * ticker `USD` must stay `USD` rather than become an empty string.
 */
export function baseSymbol(displaySymbol: string): string {
  const clean = normalizeSymbol(displaySymbol).split(':').pop() ?? '';
  for (const quote of QUOTE_SUFFIXES) {
    if (clean.length > quote.length && clean.endsWith(quote)) {
      return clean.slice(0, -quote.length);
    }
  }
  return clean;
}

/** Append when there is room, otherwise leave the list untouched. */
export function addSymbol(current: string[], symbol: string): string[] {
  const clean = normalizeSymbol(symbol);
  if (!clean || current.length >= MAX_BRIEF_SYMBOLS) return current;
  if (current.some((entry) => normalizeSymbol(entry) === clean)) return current;
  return sanitizeSymbols([...current, clean]) ?? current;
}

// ── Readings the cards draw ──────────────────────────────────────────────────

export type Tone = 'up' | 'down' | 'neutral';

/**
 * The move, in either direction and over either window, that earns a card the
 * lit rim.
 *
 * Ten percent over seven days is a run nobody has to be told about twice, and it
 * is rare enough that the effect stays meaningful: a threshold the majors clear
 * most weeks would leave the strip permanently glowing, which is the same as no
 * effect at all with more distraction.
 *
 * The band is symmetric because a 10% drawdown is the same size of news as a 10%
 * run and a reader scanning the strip needs to be pulled to both. What separates
 * them is the hue, not the threshold.
 */
export const SURGE_THRESHOLD_PCT = 10;

export interface Surge {
  hue: string;
  change: number;
  direction: 'up' | 'down';
  /** Which figure lit the rim, so the card can say so rather than leave it guessed. */
  window: '24h' | '7d';
}

/**
 * Whether this card should be lit, and in which hue.
 *
 * The day is asked first and the week second, because the day is the figure
 * printed largest on the card. Reading the week alone produced the state that
 * sent this back: PYTH at -10.75% on the session inside a +11.4% week glowed
 * green above its own red number, and a rim that contradicts the headline
 * teaches the reader to stop trusting it. The week still lights a card the day
 * leaves flat — that case is why the rim moved off the 24h change in the first
 * place, and it survives as the fallback rather than as the rule.
 *
 * The hue is returned rather than assumed by the caller so it can never disagree
 * with the figure it was computed from, and the down case is the same effect in
 * a different colour rather than a second one that drifts.
 */
export function surgeHue(change24h: number | null, change7d: number | null): Surge | null {
  const lit = (change: number, window: '24h' | '7d'): Surge => {
    const direction = change < 0 ? 'down' : 'up';
    return { hue: `var(--${direction})`, change, direction, window };
  };

  for (const [change, window] of [
    [change24h, '24h'],
    [change7d, '7d'],
  ] as const) {
    if (change === null || !Number.isFinite(change)) continue;
    if (Math.abs(change) >= SURGE_THRESHOLD_PCT) return lit(change, window);
  }
  return null;
}

/**
 * RSI as a word, matching the bands the backend's own classifier uses.
 *
 * Returned rather than computed in JSX so the thresholds live in one testable
 * place; the backend also ships `rsi_signal`, and this is the fallback for a
 * payload where the technical read produced a value but no classification.
 */
export function rsiLabel(rsi: number | null): { label: string; tone: Tone } | null {
  if (rsi === null || !Number.isFinite(rsi)) return null;
  if (rsi >= 70) return { label: 'Overbought', tone: 'down' };
  if (rsi <= 30) return { label: 'Oversold', tone: 'up' };
  if (rsi >= 55) return { label: 'Firm', tone: 'up' };
  if (rsi <= 45) return { label: 'Soft', tone: 'down' };
  return { label: 'Neutral', tone: 'neutral' };
}

/**
 * Today's turnover against its own average, as a word.
 *
 * The bands are wide because daily volume is noisy: a 1.2x session is an
 * ordinary session, and calling it "elevated" would put a badge on the card
 * roughly half the time, which is the same as putting no badge on it.
 */
export function relativeVolumeLabel(ratio: number | null): { label: string; tone: Tone } | null {
  if (ratio === null || !Number.isFinite(ratio) || ratio <= 0) return null;
  if (ratio >= 2) return { label: 'Heavy', tone: 'up' };
  if (ratio >= 1.4) return { label: 'Busy', tone: 'up' };
  if (ratio <= 0.6) return { label: 'Thin', tone: 'down' };
  return { label: 'Normal', tone: 'neutral' };
}

/**
 * Funding as basis points per interval, plus who is paying.
 *
 * Rendered in bps rather than as a percentage because the numbers are tiny —
 * "0.0100%" is four characters of leading zeros before anything varies, and the
 * card has to show the variation.
 */
export function fundingReading(
  rate: number | null,
  isExtreme: boolean | null
): { bps: number; label: string; tone: Tone; extreme: boolean } | null {
  if (rate === null || !Number.isFinite(rate)) return null;
  const bps = rate * 10_000;
  // Longs paying shorts reads as crowded-long, which is the bearish side of a
  // funding print — hence the tone, which is not the sign of the number.
  const label = bps > 0 ? 'Longs pay' : bps < 0 ? 'Shorts pay' : 'Flat';
  const tone: Tone = bps > 0 ? 'down' : bps < 0 ? 'up' : 'neutral';
  return { bps, label, tone, extreme: Boolean(isExtreme) };
}

/** Which way a percentage change should be coloured. */
export function changeTone(change: number | null): Tone {
  if (change === null || !Number.isFinite(change) || change === 0) return 'neutral';
  return change > 0 ? 'up' : 'down';
}

/**
 * Where price sits between the nearest support and resistance, 0–1.
 *
 * Null unless both bounds exist and bracket the price: a bar drawn from one
 * bound and a guess would be a picture of a measurement that was not taken.
 */
export function rangePosition(brief: AssetBrief): number | null {
  const { support, resistance, price } = brief;
  if (support === null || resistance === null) return null;
  if (!(resistance > support) || price < support || price > resistance) return null;
  return (price - support) / (resistance - support);
}

/** Percentage formatted with an explicit sign, or an em dash. */
export function formatSignedPercent(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

/** Compact turnover: `$1.2B`, `$840M`. Shares when `currency` is false. */
export function formatCompact(value: number | null, currency = true): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const prefix = currency ? '$' : '';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${prefix}${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${prefix}${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${prefix}${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${prefix}${(value / 1e3).toFixed(1)}K`;
  return `${prefix}${value.toFixed(0)}`;
}

/** Tailwind text colour for a tone. Literal classes — Tailwind cannot see built ones. */
export const TONE_TEXT: Record<Tone, string> = {
  up: 'text-up',
  down: 'text-down',
  neutral: 'text-fg-muted',
};
