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

/** Background classes for a bar drawn in an asset's own colour. */
export interface IdentityBarClasses {
  /** The filled span. Rendered at reduced opacity by its caller. */
  fill: string;
  /** The position marker, which carries the hue at full strength. */
  marker: string;
}

/**
 * The same identities as background fills, for the bars beside the names.
 *
 * Spelled out again rather than derived from `IDENTITY_CLASS` with a string
 * swap: Tailwind reads source text, so `text-data-gold` rewritten to
 * `bg-data-gold` at runtime is a class that was never generated. Same reason the
 * map above is literal.
 */
const IDENTITY_BAR: Record<string, IdentityBarClasses> = {
  'GC=F': { fill: 'bg-data-gold', marker: 'bg-data-gold' },
  'SI=F': { fill: 'bg-data-silver', marker: 'bg-data-silver' },
  'PL=F': { fill: 'bg-data-platinum', marker: 'bg-data-platinum' },
  'PA=F': { fill: 'bg-data-palladium', marker: 'bg-data-palladium' },
  'HG=F': { fill: 'bg-data-copper', marker: 'bg-data-copper' },

  GOLD: { fill: 'bg-data-gold', marker: 'bg-data-gold' },
  XAU: { fill: 'bg-data-gold', marker: 'bg-data-gold' },
  SILVER: { fill: 'bg-data-silver', marker: 'bg-data-silver' },
  XAG: { fill: 'bg-data-silver', marker: 'bg-data-silver' },
  PLATINUM: { fill: 'bg-data-platinum', marker: 'bg-data-platinum' },
  XPT: { fill: 'bg-data-platinum', marker: 'bg-data-platinum' },
  PALLADIUM: { fill: 'bg-data-palladium', marker: 'bg-data-palladium' },
  XPD: { fill: 'bg-data-palladium', marker: 'bg-data-palladium' },
  COPPER: { fill: 'bg-data-copper', marker: 'bg-data-copper' },

  BTC: { fill: 'bg-data-btc', marker: 'bg-data-btc' },
  ETH: { fill: 'bg-data-eth', marker: 'bg-data-eth' },
};

/** Bar classes for an asset, or `undefined` where the neutral bar is correct. */
export function assetIdentityBarClasses(
  symbol: string | null | undefined
): IdentityBarClasses | undefined {
  if (!symbol) return undefined;
  return IDENTITY_BAR[symbol] ?? IDENTITY_BAR[symbol.toUpperCase()];
}
