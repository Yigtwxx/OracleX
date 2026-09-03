import { normalizeSymbol } from '@/lib/asset-brief';
import type { MarketType } from '@/lib/asset-logo';

/**
 * One row the brief's picker can offer.
 *
 * `source` is what the row says about itself on the right — the watchlist it
 * came from, or the asset class it belongs to. It is carried rather than derived
 * at render so a symbol that appears in two places is labelled by the one that
 * actually supplied it.
 */
export interface AssetOption {
  symbol: string;
  name: string;
  marketType: MarketType;
  logo?: string | null;
  source: string;
  /** Market-cap rank, where the source reports one. Orders the unfiltered list. */
  rank?: number | null;
}

/**
 * Merge sources into one list, first mention winning.
 *
 * Call it with the watchlists ahead of the market boards: a symbol the reader
 * already follows should be labelled with their own list's name rather than
 * with "Crypto", and the rank the board would have added is not what they are
 * scanning for.
 */
export function mergeAssetOptions(...groups: AssetOption[][]): AssetOption[] {
  const seen = new Set<string>();
  const merged: AssetOption[] = [];
  for (const group of groups) {
    for (const option of group) {
      const symbol = normalizeSymbol(option.symbol);
      if (!symbol || seen.has(symbol)) continue;
      seen.add(symbol);
      merged.push({ ...option, symbol });
    }
  }
  return merged;
}

/**
 * How well one row answers what was typed. Lower is better; null is "not an
 * answer at all".
 *
 * The tiers exist because a substring match is not the same kind of hit as a
 * ticker the reader typed in full: someone who types `ADA` wants Cardano first,
 * not every coin that merely starts with those letters.
 *
 * Names are matched at word starts, never anywhere in the string. A raw
 * substring test looks harmless and is not — `ADA` pulled in "Tr**ada**ble
 * Singapore Fintech SSL" and "Met**aDA**O" ahead of half the board, and a list
 * whose top rows are visibly unrelated to the query reads as broken regardless
 * of what sits at row one.
 */
export function matchScore(option: AssetOption, needle: string): number | null {
  if (!needle) return 0;
  const symbol = option.symbol.toUpperCase();

  if (symbol === needle) return 0;
  if (symbol.startsWith(needle)) return 1;
  if (nameWords(option.name).some((word) => word.startsWith(needle))) return 2;
  if (symbol.includes(needle)) return 3;
  return null;
}

/**
 * A rank that sorts, with every way of saying "unranked" pushed to the end.
 *
 * A null check alone is not enough: the market board reports an unranked asset
 * as rank **0**, not as null, and `?? MAX` lets a 0 through — which is how
 * "Tradable Singapore Fintech SSL" came to sit above Bitcoin at the top of an
 * empty query.
 */
function sortableRank(rank: number | null | undefined): number {
  return typeof rank === 'number' && rank > 0 ? rank : Number.MAX_SAFE_INTEGER;
}

/** A display name split into the words a reader would search it by. */
function nameWords(name: string): string[] {
  return name
    .toUpperCase()
    .split(/[^A-Z0-9]+/)
    .filter(Boolean);
}

/**
 * The rows to show, best first.
 *
 * Ties break on market-cap rank so an unfiltered list opens with the assets most
 * people mean, and an unranked row sorts last rather than first — a missing rank
 * is unknown, not zero, and treating it as zero once put obscure watchlist
 * entries above BTC.
 */
export function searchAssets(options: AssetOption[], query: string, limit = 40): AssetOption[] {
  const needle = normalizeSymbol(query);

  return options
    .map((option) => ({ option, score: matchScore(option, needle) }))
    .filter((row): row is { option: AssetOption; score: number } => row.score !== null)
    .sort((a, b) => {
      if (a.score !== b.score) return a.score - b.score;
      const rankA = sortableRank(a.option.rank);
      const rankB = sortableRank(b.option.rank);
      if (rankA !== rankB) return rankA - rankB;
      return a.option.symbol.localeCompare(b.option.symbol);
    })
    .slice(0, limit)
    .map((row) => row.option);
}
