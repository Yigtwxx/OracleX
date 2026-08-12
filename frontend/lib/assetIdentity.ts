/**
 * Which asset names wear their own colour.
 *
 * Identity, never direction: the hue names the instrument. A gold row is this
 * colour whether gold is up or down — green and red stay entirely on the delta
 * beside it, so nothing here can be misread as a status. That rule is why cash
 * is deliberately absent from this map: the only free colour left would read as
 * a gain.
 *
 * A literal map of complete class strings. Tailwind scans source text, so a
 * class assembled from a variable (`text-data-${metal}`) is never generated and
 * the row silently renders in the default colour — see the `lib/` glob comment
 * in tailwind.config.ts, which exists because of exactly that bug.
 *
 * Keyed on both the futures contract the macro board trades in and the plain
 * symbol a holdings row reports, because the same metal arrives under two names
 * depending on which page asked.
 */
const IDENTITY_CLASS: Record<string, string> = {
  // Futures contracts — the macro board's vocabulary.
  'GC=F': 'text-data-gold metal-sheen',
  'SI=F': 'text-data-silver metal-sheen',
  'PL=F': 'text-data-platinum metal-sheen',
  'PA=F': 'text-data-palladium metal-sheen',
  'HG=F': 'text-data-copper metal-sheen',

  // Spot and holdings vocabulary — what a reserve or a treasury line reports.
  GOLD: 'text-data-gold metal-sheen',
  XAU: 'text-data-gold metal-sheen',
  SILVER: 'text-data-silver metal-sheen',
  XAG: 'text-data-silver metal-sheen',
  PLATINUM: 'text-data-platinum metal-sheen',
  XPT: 'text-data-platinum metal-sheen',
  PALLADIUM: 'text-data-palladium metal-sheen',
  XPD: 'text-data-palladium metal-sheen',
  COPPER: 'text-data-copper metal-sheen',

  // Crypto identity, on the same terms.
  BTC: 'text-data-btc',
  ETH: 'text-data-eth',
};

/** Classes for an asset's name, or the ordinary foreground for everything else. */
export function assetIdentityClass(
  symbol: string | null | undefined,
  fallback = 'text-fg'
): string {
  if (!symbol) return fallback;
  return IDENTITY_CLASS[symbol] ?? IDENTITY_CLASS[symbol.toUpperCase()] ?? fallback;
}
