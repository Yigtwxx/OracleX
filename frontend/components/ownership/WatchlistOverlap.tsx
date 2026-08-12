'use client';

import { useWatchlistOverlap } from '@/hooks/queries';
import { assetIdentityClass } from '@/lib/assetIdentity';
import { formatUsd } from './format';

interface WatchlistOverlapProps {
  onSelectAsset?: (symbol: string) => void;
}

/**
 * Where the reader's own watchlist meets the holders on this page.
 *
 * Renders nothing at all when there is no overlap — not an empty box, not a
 * "nothing here" line. A strip that only appears when it has something to say
 * costs nothing when it is silent, whereas a permanent empty panel is a
 * standing reminder that a feature did not work.
 */
export default function WatchlistOverlap({ onSelectAsset }: WatchlistOverlapProps) {
  const overlap = useWatchlistOverlap();
  const rows = overlap.data?.overlap ?? [];

  if (overlap.isLoading || overlap.isError || rows.length === 0) return null;

  return (
    <div>
      <p className="label mb-1.5">On your watchlist</p>
      <div className="custom-scrollbar flex gap-2 overflow-x-auto pb-1">
        {rows.map((row) => {
          const symbol = row.symbol ?? row.label;
          const holders = row.holders ?? row.holder_names ?? [];
          const content = (
            <>
              <span className={`text-xs font-medium ${assetIdentityClass(symbol)}`}>{symbol}</span>
              <span className="whitespace-nowrap text-2xs text-fg-muted">
                {row.holder_count === 1 ? '1 holder' : `${row.holder_count} holders`}
              </span>
              <span className="tabnum whitespace-nowrap text-2xs text-fg-subtle">
                {formatUsd(row.total_value_usd)}
              </span>
            </>
          );

          return onSelectAsset && row.symbol ? (
            <button
              key={symbol}
              type="button"
              onClick={() => onSelectAsset(row.symbol as string)}
              title={holders.join(', ')}
              className="surface flex shrink-0 items-center gap-2 px-2.5 py-1.5 transition-colors hover:bg-surface-2"
            >
              {content}
            </button>
          ) : (
            <span
              key={symbol}
              title={holders.join(', ')}
              className="surface flex shrink-0 items-center gap-2 px-2.5 py-1.5"
            >
              {content}
            </span>
          );
        })}
      </div>
    </div>
  );
}
