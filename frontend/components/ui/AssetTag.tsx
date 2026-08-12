'use client';

/**
 * The asset a news item was attributed to.
 *
 * Not every headline is about a tradeable asset — rate decisions, index recaps
 * and regulatory copy are not — and the backend returns `symbol: null` for
 * those rather than guessing. The two states have to look different: the feed
 * used to fall back to printing the publisher in the ticker slot, so "Tree of
 * Alpha" sat exactly where "BTCUSDT" sits and read as one.
 */
interface AssetTagProps {
  /** TradingView symbol, e.g. `OKX:BTCUSDT` or `NASDAQ:AAPL`. */
  symbol?: string;
  size?: 'sm' | 'md';
}

export default function AssetTag({ symbol, size = 'sm' }: AssetTagProps) {
  const text = size === 'sm' ? 'text-xs' : 'text-sm';

  if (!symbol) {
    return (
      <span className={`${text} font-mono text-fg-subtle`} title="No specific asset">
        —
      </span>
    );
  }

  const ticker = symbol.includes(':') ? symbol.split(':')[1] : symbol;

  return (
    <span
      className={`${text} font-mono text-fg bg-surface-2 border border-line rounded px-1.5 py-0.5`}
      title={symbol}
    >
      {ticker}
    </span>
  );
}
