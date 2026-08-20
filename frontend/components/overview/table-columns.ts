import { CoinData } from '@/lib/api';

// Columns the asset table can show on top of its fixed set. Everything here is
// derived from the market-overview payload the table already renders — no extra
// request. The option list is short for that reason: `CoinData` carries no 1h
// or 30d change, no FDV and no supply, so there is nothing to expose for them.

export type ColumnKey = 'range24h' | 'turnover' | 'high24h' | 'low24h' | 'range52w';

export interface ColumnDef {
  key: ColumnKey;
  label: string;
  width: string;
  /** Set when only one of the two markets reports the source field. */
  marketType?: 'crypto' | 'nasdaq';
}

export const OPTIONAL_COLUMNS: ColumnDef[] = [
  { key: 'range24h', label: '24h Range', width: '110px' },
  { key: 'turnover', label: 'Vol / MCap', width: '90px' },
  { key: 'high24h', label: '24h High', width: '100px' },
  { key: 'low24h', label: '24h Low', width: '100px' },
  { key: 'range52w', label: '52W Range', width: '110px', marketType: 'nasdaq' },
];

export const DEFAULT_COLUMNS: ColumnKey[] = ['range24h'];

export const columnsForMarket = (marketType: 'crypto' | 'nasdaq'): ColumnDef[] =>
  OPTIONAL_COLUMNS.filter((c) => !c.marketType || c.marketType === marketType);

/**
 * Share of market cap that changed hands in 24h, as a percentage. Returns
 * undefined when market cap is missing or zero — a row with no denominator
 * renders `--` rather than Infinity.
 */
export const turnoverPct = (coin: CoinData): number | undefined => {
  if (!coin.market_cap || coin.market_cap <= 0) return undefined;
  if (coin.volume_24h == null || Number.isNaN(coin.volume_24h)) return undefined;
  return (coin.volume_24h / coin.market_cap) * 100;
};

/**
 * Where the current price sits inside a low–high band, 0–1. Returns undefined
 * when the band is missing or degenerate (high <= low), which is what an
 * untraded or partially-reported row looks like.
 */
export const rangePosition = (
  low: number | undefined,
  high: number | undefined,
  price: number
): number | undefined => {
  if (low == null || high == null) return undefined;
  if (!Number.isFinite(low) || !Number.isFinite(high)) return undefined;
  if (high <= low) return undefined;
  return Math.min(1, Math.max(0, (price - low) / (high - low)));
};

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

const COLUMNS_STORAGE_KEY = 'oraclex.overview.columns';

// localStorage is unavailable during SSR and can throw in private-mode Safari,
// so access is guarded and falls back to the in-code default. A forgotten
// preference is a non-event; a crashed table is not.
export const loadColumns = (): ColumnKey[] => {
  if (typeof window === 'undefined') return DEFAULT_COLUMNS;
  try {
    const raw = window.localStorage.getItem(COLUMNS_STORAGE_KEY);
    if (!raw) return DEFAULT_COLUMNS;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return DEFAULT_COLUMNS;
    const valid = new Set<string>(OPTIONAL_COLUMNS.map((c) => c.key));
    return parsed.filter((k): k is ColumnKey => typeof k === 'string' && valid.has(k));
  } catch {
    return DEFAULT_COLUMNS;
  }
};

export const saveColumns = (columns: ColumnKey[]): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(columns));
  } catch {
    /* quota or disabled storage — the session still works, it just forgets */
  }
};
