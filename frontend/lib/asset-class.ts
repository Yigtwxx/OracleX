/**
 * Which market a news item belongs to — the feed mixes two of them.
 *
 * The item's `asset_type` cannot answer this on its own: the backend defaults
 * it to the feed the item arrived on, so a headline no detector could attribute
 * to any ticker still comes back as "crypto" simply because it was pulled from
 * a crypto wire. Reading that as a fact would paint half the feed with a
 * confidence the data does not have.
 *
 * The resolved `symbol` is the fact. It exists only when attribution actually
 * succeeded, and its exchange prefix (`NASDAQ:NVDA`, `BINANCE:BTCUSDT`) names
 * the market outright. When there is no symbol — or an exchange neither side
 * claims — the honest answer is `unknown`, and the row says so in grey rather
 * than guessing.
 */

import type { NewsItem } from '@/store/useStore';

export type AssetClass = 'stock' | 'crypto' | 'unknown';

/**
 * Mirrors `EQUITY_EXCHANGES` / `CRYPTO_EXCHANGES` in
 * `backend/services/symbol_detection_service.py`. Symbols are minted there, so
 * a prefix that is not in these sets is one this UI has not been taught yet —
 * `unknown` is the correct output for it, not a coin flip.
 */
const EQUITY_EXCHANGES = new Set(['NASDAQ', 'NYSE']);
const CRYPTO_EXCHANGES = new Set(['BINANCE', 'OKX']);

/** The market a headline was attributed to, or `unknown` if it was not. */
export function assetClassOf(news: Pick<NewsItem, 'symbol'>): AssetClass {
  const symbol = news.symbol;
  if (!symbol || !symbol.includes(':')) return 'unknown';

  const exchange = symbol.split(':')[0].toUpperCase();
  if (EQUITY_EXCHANGES.has(exchange)) return 'stock';
  if (CRYPTO_EXCHANGES.has(exchange)) return 'crypto';
  return 'unknown';
}

/** What the row's stripe means, spelled out for the tooltip. */
export const ASSET_CLASS_LABEL: Record<AssetClass, string> = {
  stock: 'Stock market news',
  crypto: 'Crypto market news',
  unknown: 'Market could not be determined',
};
