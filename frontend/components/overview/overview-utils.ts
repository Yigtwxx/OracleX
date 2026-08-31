import { FearGreedData, MarketOverview } from '@/lib/api';

// Asset marks used to be resolved here, as one guessed URL with no way back
// when it missed. They now live in `lib/asset-logo.ts` as an ordered chain that
// `components/ui/AssetLogo.tsx` walks in the browser — see the note there for
// why a single ticker-derived host could never work.

// Get asset name
export const getAssetName = (symbol: string, providedName?: string): string =>
  providedName || symbol;

// The 7d change and the sparkline series used to be generated here from a
// seeded PRNG — plausible-looking numbers that were not market data. Both now
// arrive on the API payload (`change_7d`, `sparkline`), so a row that has no
// real series renders nothing rather than something invented.

// Formatters
export const formatPrice = (price: number) => {
  if (price >= 1000) {
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (price >= 1) {
    return `$${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  // For very small prices (e.g. SHIB, PEPE), show more decimals
  return `$${price.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })}`;
};

export const formatLargeNumber = (num: number) => {
  if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
  if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
  if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
  return `$${num.toLocaleString('en-US')}`;
};

export const formatVolume = (num: number) => {
  if (num === undefined || num === null || isNaN(num)) return '--';
  if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
  if (num >= 1e9) return `$${(num / 1e9).toFixed(1)}B`;
  if (num >= 1e6) return `$${(num / 1e6).toFixed(1)}M`;
  return `$${num.toLocaleString('en-US')}`;
};

// Fear -> greed is a diverging scale, so colour here encodes the value itself.
export const getFearGreedColor = (value: number) => {
  if (value <= 45) return 'var(--down)';
  if (value <= 55) return 'var(--warn)';
  return 'var(--up)';
};
