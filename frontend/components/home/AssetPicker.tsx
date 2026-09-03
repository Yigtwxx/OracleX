'use client';

import { useMemo, useState } from 'react';
import Modal from '@/components/ui/Modal';
import AssetLogo from '@/components/ui/AssetLogo';
import { useMarketOverview, useNasdaqOverview, useWatchlists } from '@/hooks/queries';
import { normalizeSymbol } from '@/lib/asset-brief';
import { mergeAssetOptions, searchAssets, type AssetOption } from '@/lib/asset-search';

interface AssetPickerProps {
  isOpen: boolean;
  /** What the slot currently holds, so it can be marked and excluded. */
  current: string | null;
  /** The other slots' symbols — offering one of them would make a duplicate. */
  taken: string[];
  onClose: () => void;
  onPick: (symbol: string) => void;
  /** Absent for the "add a slot" flow, where there is nothing to remove. */
  onRemove?: () => void;
}

/**
 * Choose what goes in one brief slot.
 *
 * The watchlist is a source here, not the store. Binding the strip to a
 * watchlist would have meant a signed-out visitor gets an empty board and a
 * login wall on the first thing they see, and it would have meant a new
 * mutation endpoint for "add one symbol" that nothing else needs. So the slots
 * live in localStorage and the watchlist just fills the suggestion list.
 *
 * Free text is not validated here. The backend resolves `pepe`, `$NVDA` and
 * `BINANCE:ETHUSDT` alike and answers 404 for what it cannot place — duplicating
 * a slice of that in the browser would produce a second, wronger resolver whose
 * disagreements show up as "this symbol is invalid" for symbols that work.
 *
 * What the list does do is *recognise*: the two market boards the terminal has
 * already loaded are searched alongside the watchlists, and every row carries
 * the asset's own mark. Typing `ADA` used to answer "nothing here matches" and
 * leave the reader to trust that a bare ticker would resolve; it now answers
 * with Cardano's logo and name, which is the difference between guessing and
 * choosing.
 */
export default function AssetPicker({
  isOpen,
  current,
  taken,
  onClose,
  onPick,
  onRemove,
}: AssetPickerProps) {
  const [query, setQuery] = useState('');
  const watchlists = useWatchlists();
  // Both boards are already in the cache on Home, and gating them on `isOpen`
  // keeps a picker that is never opened from fetching them anywhere else.
  const crypto = useMarketOverview(isOpen);
  const equities = useNasdaqOverview(isOpen);

  const isLoading = watchlists.isLoading || crypto.isLoading || equities.isLoading;

  const options = useMemo<AssetOption[]>(() => {
    const held = new Set(taken.map(normalizeSymbol));

    const fromWatchlists: AssetOption[] = (watchlists.data ?? []).flatMap((list) =>
      list.items.map((item) => ({
        symbol: item.symbol,
        name: item.name ?? item.symbol,
        marketType: item.type === 'STOCK' ? ('nasdaq' as const) : ('crypto' as const),
        logo: item.logo ?? null,
        source: list.name,
      }))
    );

    const fromCrypto: AssetOption[] = (crypto.data?.coins ?? []).map((coin) => ({
      symbol: coin.symbol,
      name: coin.name,
      marketType: 'crypto' as const,
      logo: coin.logo,
      source: 'Crypto',
      rank: coin.market_cap_rank,
    }));

    const fromEquities: AssetOption[] = (equities.data?.coins ?? []).map((row) => ({
      symbol: row.symbol,
      name: row.name,
      marketType: 'nasdaq' as const,
      logo: row.logo,
      source: 'Equity',
      rank: row.market_cap_rank,
    }));

    // A slot the reader already holds is not an option — offering it would make
    // a duplicate the slot list would then silently drop.
    return mergeAssetOptions(fromWatchlists, fromCrypto, fromEquities).filter(
      (option) => !held.has(option.symbol)
    );
  }, [watchlists.data, crypto.data, equities.data, taken]);

  const suggestions = useMemo(() => searchAssets(options, query), [options, query]);

  const typed = normalizeSymbol(query);
  const submit = (symbol: string) => {
    const clean = normalizeSymbol(symbol);
    if (!clean) return;
    onPick(clean);
    setQuery('');
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Choose an asset" maxWidth="max-w-md">
      <div className="p-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit(typed);
          }}
        >
          <label htmlFor="brief-asset" className="label">
            Symbol
          </label>
          <div className="mt-1.5 flex gap-2">
            <input
              id="brief-asset"
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="BTCUSDT, NVDA, ETH…"
              className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-fg placeholder:text-fg-subtle focus:border-line-strong focus:outline-none"
            />
            <button
              type="submit"
              disabled={!typed}
              className="shrink-0 rounded border border-line px-3 py-1.5 text-xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-40"
            >
              Use
            </button>
          </div>
          <p className="mt-1.5 text-2xs text-fg-subtle">
            Crypto pairs and US tickers both work. An exchange prefix is optional.
          </p>
        </form>

        <div className="mt-4">
          <span className="label">{query ? 'Matches' : 'Popular and from your watchlists'}</span>
          <div className="mt-1.5 max-h-72 overflow-y-auto overflow-x-hidden custom-scrollbar">
            {isLoading && !suggestions.length ? (
              <div className="h-16 shimmer rounded" aria-hidden />
            ) : suggestions.length ? (
              <ul className="divide-y divide-line">
                {suggestions.map((row) => (
                  <li key={row.symbol}>
                    <button
                      onClick={() => submit(row.symbol)}
                      className="flex w-full items-center gap-2.5 px-1 py-2 text-left transition-colors hover:bg-surface-2"
                    >
                      {/* The mark is what makes this list scannable — a column of
                          tickers reads as text to be parsed, a column of logos
                          reads as things to pick from. */}
                      <AssetLogo
                        symbol={row.symbol}
                        providedLogo={row.logo}
                        marketType={row.marketType}
                        size={40}
                        className="h-6 w-6 shrink-0 rounded-full bg-surface-2 object-cover"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-fg">{row.symbol}</span>
                        <span className="block truncate text-2xs text-fg-subtle">{row.name}</span>
                      </span>
                      <span className="shrink-0 text-2xs text-fg-subtle">{row.source}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              // Nothing matched, which is not the same as nothing being loaded.
              // The typed symbol still works — the backend resolves far more
              // than these two boards list — so the line points back at it
              // rather than reading as a dead end.
              <p className="py-3 text-2xs text-fg-subtle">
                No asset here matches “{query}”. The symbol may still resolve — press Use to try it.
              </p>
            )}
          </div>
        </div>

        {onRemove && current && (
          <div className="mt-4 border-t border-line pt-3">
            <button
              onClick={() => {
                onRemove();
                onClose();
              }}
              className="text-2xs text-fg-subtle transition-colors hover:text-down"
            >
              Remove {current} from the brief
            </button>
          </div>
        )}
      </div>
    </Modal>
  );
}
