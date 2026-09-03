import { baseSymbol } from '@/lib/asset-brief';

/**
 * Where an asset's mark comes from, and what to do when it is not there.
 *
 * The board used to derive one URL per asset from `cryptologos.cc` and treat a
 * miss as final. That host names its files after the coin's *slug*, not its
 * ticker — `bitcoin-btc-logo.png`, never `btc-btc-logo.png` — so every
 * symbol-derived URL 404'd and the whole terminal fell through to initials on a
 * grey circle. A single source that cannot be addressed by ticker is not a
 * source; what replaces it is an ordered chain, tried in the browser.
 */
export type MarketType = 'crypto' | 'nasdaq';

/**
 * Crypto marks, broad coverage first.
 *
 * CoinCap carries the long tail this board actually shows — PEPE, SUI, TON, ARB,
 * OP — and answers 404 rather than a placeholder for a ticker it does not know,
 * which is what makes it safe to fall through. The jsDelivr package sits behind
 * it as the durable half of the pair: narrower (majors only) but on a CDN that
 * is not one company's asset host.
 */
const CRYPTO_SOURCES: ((symbol: string) => string)[] = [
  (symbol) => `https://assets.coincap.io/assets/icons/${symbol.toLowerCase()}@2x.png`,
  (symbol) =>
    `https://cdn.jsdelivr.net/npm/cryptocurrency-icons@0.18.1/128/color/${symbol.toLowerCase()}.png`,
];

const EQUITY_SOURCES: ((symbol: string) => string)[] = [
  (symbol) => `https://financialmodelingprep.com/image-stock/${symbol.toUpperCase()}.png`,
];

/** Initials on the board's own surface colour — the end of every chain. */
export function avatarFallback(symbol: string, size: number): string {
  const name = encodeURIComponent(symbol.toUpperCase());
  return `https://ui-avatars.com/api/?name=${name}&background=232328&color=e8e8ea&size=${size}&bold=true`;
}

/**
 * Every URL worth trying for one asset, best first, initials last.
 *
 * A payload's own `logo` wins outright: the backend resolved that asset and knows
 * its mark, and second-guessing it here would replace a correct image with a
 * guess. The chain is never empty — the last entry always renders something.
 */
export function logoCandidates(
  symbol: string,
  providedLogo: string | null | undefined,
  marketType: MarketType,
  size = 64
): string[] {
  // The pair carries its venue and its quote currency; the mark belongs to the
  // asset. `BTCUSDT` asking for a `btcusdt` icon is a guaranteed miss.
  const asset = marketType === 'crypto' ? baseSymbol(symbol) : symbol.trim().toUpperCase();
  const sources = marketType === 'crypto' ? CRYPTO_SOURCES : EQUITY_SOURCES;

  const chain = providedLogo ? [providedLogo] : [];
  if (asset) chain.push(...sources.map((build) => build(asset)));
  chain.push(avatarFallback(asset || symbol, size));

  // A backend logo that happens to equal a derived one must not be tried twice:
  // the second attempt would fail identically and only cost a request.
  return chain.filter((url, index) => chain.indexOf(url) === index);
}
