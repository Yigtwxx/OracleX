import { FearGreedData, MarketOverview } from '@/lib/api';

// Logo/name for an asset come from the API payload; these are the fallbacks
// used when a response omits them. Deriving the URL from the symbol keeps new
// assets working without a per-symbol lookup table to maintain.

// Get logo URL for a coin
export const getCoinLogo = (symbol: string): string =>
  `https://cryptologos.cc/logos/${symbol.toLowerCase()}-${symbol.toLowerCase()}-logo.png?v=035`;

// Get logo URL for a stock
export const getStockLogo = (symbol: string): string =>
  `https://financialmodelingprep.com/image-stock/${symbol.toUpperCase()}.png`;

// Get logo for any asset type
export const getAssetLogo = (
  symbol: string,
  providedLogo?: string,
  marketType: 'crypto' | 'nasdaq' = 'crypto'
): string => {
  if (providedLogo) {
    return providedLogo;
  }
  if (marketType === 'nasdaq') {
    return getStockLogo(symbol);
  }
  return getCoinLogo(symbol);
};

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
