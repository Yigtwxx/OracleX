/**
 * Shared formatting for the Ownership board.
 *
 * The board mixes a $55bn treasury with a 43,000-coin balance and a share
 * count, so nothing here takes a fixed precision — every formatter picks its
 * shape from the magnitude it is handed.
 *
 * `UNKNOWN` is load-bearing. A position whose USD value nobody published is
 * null, and it has to render as a dash rather than a zero: "$0" is a claim that
 * the holding is worthless, which is a different statement from "we do not know
 * what it is worth".
 */

import type { OwnershipAssetClass, OwnershipCategory, OwnershipMoveKind } from '@/lib/api';
import { brandColor, tooClose } from '@/lib/brandColors';

/** Shown wherever a figure could not be sourced. Never a 0. */
export const UNKNOWN = 'Unknown';

/** Compact USD, e.g. "$54.9B", "$316M", "$1.4K". */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN;
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(2)}`;
}

/**
 * A holding count with its unit, e.g. "842,137 BTC", "29.4 tonnes".
 *
 * Fractional digits track magnitude: a bitcoin balance of 9,542.16 keeps its
 * cents-equivalent, a balance of 842,137 does not need them.
 */
export function formatQuantity(
  quantity: number | null | undefined,
  unit: string | null | undefined
): string {
  if (quantity === null || quantity === undefined || !Number.isFinite(quantity)) return UNKNOWN;

  // A cash line's quantity *is* its value, so spelling out 15,219,000,000 USD
  // beside "$15.22B" prints the same fact twice and in the harder-to-read form.
  if (unit === 'USD') return formatUsd(quantity);

  const abs = Math.abs(quantity);
  const decimals = abs >= 10000 ? 0 : abs >= 100 ? 2 : abs >= 1 ? 4 : 6;
  const text = quantity.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
  return unit ? `${text} ${unit}` : text;
}

export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNKNOWN;
  return `${value.toFixed(decimals)}%`;
}

/** "12 Mar 2026" — unambiguous across locales, unlike a numeric date. */
export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * Fill colour per asset class, as complete literal class strings.
 *
 * Identity again, not a palette: gold is the gold token and BTC is the BTC
 * token, so two entities' bars stay comparable — which is the one thing the bar
 * exists to allow. Cash takes a neutral grey rather than a hue, because every
 * remaining colour would read as direction.
 */
export const ASSET_CLASS_FILL: Record<OwnershipAssetClass, string> = {
  equity: 'bg-chart-1',
  crypto: 'bg-data-btc',
  gold: 'bg-data-gold',
  // Neutral grey, not a hue. Every colour still free would read as direction —
  // and the amber it used to wear was a shade off the bitcoin orange beside it,
  // so a treasury's cash and its coins were indistinguishable on the same bar.
  cash: 'bg-chart-6',
  fx_reserve: 'bg-chart-2',
  bond: 'bg-chart-5',
  fund: 'bg-chart-3',
  other: 'bg-chart-4',
};

/** The pooled tail of small holdings. Mirrors `POOLED_SLICE_KEY` on the API. */
export const POOLED_SLICE_KEY = '__other__';

/**
 * The two class strings one holding wears: the bar segment and its name.
 *
 * Paired on purpose. The card lists its largest holdings under the bar, and the
 * only thing tying "Coca Cola Co" to the segment that represents it is that
 * they are the same colour — so the fill and the text colour are defined
 * together and can never drift apart.
 */
export interface SliceColor {
  /** Tailwind class for the bar segment. Empty when the colour is a `hex`. */
  fill: string;
  /** Tailwind class for the holding's name. Empty when the colour is a `hex`. */
  text: string;
  /**
   * A literal colour, for the brands that arrive as data rather than as theme.
   * A ticker's colour cannot be a design token — there are forty of them and
   * they belong to their owners, not to this app's palette.
   */
  hex?: string;
}

/**
 * Colours per asset name. Same rule as `assetIdentityClass`: the hue names the
 * instrument, so bitcoin is bitcoin orange in a bar and in a row, and never a
 * shade of "up".
 */
const IDENTITY_COLOR: Record<string, SliceColor> = {
  BTC: { fill: 'bg-data-btc', text: 'text-data-btc' },
  ETH: { fill: 'bg-data-eth', text: 'text-data-eth' },
  GOLD: { fill: 'bg-data-gold', text: 'text-data-gold' },
  XAU: { fill: 'bg-data-gold', text: 'text-data-gold' },
  SILVER: { fill: 'bg-data-silver', text: 'text-data-silver' },
  XAG: { fill: 'bg-data-silver', text: 'text-data-silver' },
  PLATINUM: { fill: 'bg-data-platinum', text: 'text-data-platinum' },
  XPT: { fill: 'bg-data-platinum', text: 'text-data-platinum' },
  PALLADIUM: { fill: 'bg-data-palladium', text: 'text-data-palladium' },
  XPD: { fill: 'bg-data-palladium', text: 'text-data-palladium' },
  COPPER: { fill: 'bg-data-copper', text: 'text-data-copper' },
};

const CASH_COLOR: SliceColor = { fill: 'bg-chart-6', text: 'text-chart-6' };
const POOLED_COLOR: SliceColor = { fill: 'bg-chart-6/50', text: 'text-chart-6' };

/**
 * The rotation a holding with no colour of its own draws from.
 *
 * Neighbouring entries are deliberately far apart in hue: the whole point of
 * the bar is that two adjacent segments read as two holdings, and indigo beside
 * teal does that where indigo beside blue does not. The second lap is the same
 * hues at reduced opacity, which stays distinguishable from its solid twin
 * without inventing a colour that would read as direction.
 */
const SLICE_PALETTE: SliceColor[] = [
  { fill: 'bg-chart-1', text: 'text-chart-1' },
  { fill: 'bg-chart-2', text: 'text-chart-2' },
  { fill: 'bg-chart-3', text: 'text-chart-3' },
  { fill: 'bg-chart-5', text: 'text-chart-5' },
  { fill: 'bg-chart-4', text: 'text-chart-4' },
  { fill: 'bg-chart-1/55', text: 'text-chart-1/70' },
  { fill: 'bg-chart-2/55', text: 'text-chart-2/70' },
  { fill: 'bg-chart-3/55', text: 'text-chart-3/70' },
  { fill: 'bg-chart-5/55', text: 'text-chart-5/70' },
  { fill: 'bg-chart-4/55', text: 'text-chart-4/70' },
];

/**
 * A colour per slice, resolved for the whole bar at once.
 *
 * Together rather than one at a time because the constraint is between the
 * segments: a colour already spent on an earlier slice is skipped, so no bar
 * ever shows the same fill twice and every boundary is a real boundary.
 */
export function allocationColors(
  slices: { key: string; symbol: string | null; asset_class: OwnershipAssetClass }[]
): SliceColor[] {
  const used = new Set<string>();
  const claimedHexes: string[] = [];

  // Identity first, so a fixed colour claims its hue before the rotation can
  // hand it to something else.
  const identities = slices.map((slice) => {
    if (slice.key === POOLED_SLICE_KEY) return POOLED_COLOR;
    // A board written before the bar went per-holding carries class slices and
    // no key. Colouring those by class is what they mean; running them through
    // the rotation would repaint yesterday's bar in arbitrary hues.
    if (!slice.key) return { fill: ASSET_CLASS_FILL[slice.asset_class], text: 'text-fg' };
    // Cash keeps the neutral grey it has always had. Every colour still free
    // would read as direction.
    if (slice.asset_class === 'cash') return CASH_COLOR;

    const color = slice.symbol ? IDENTITY_COLOR[slice.symbol.toUpperCase()] : undefined;
    if (color) {
      used.add(color.fill);
      return color;
    }

    // The company's own colour, if it has one and nothing beside it in this bar
    // has already taken that hue. Coca-Cola red and Netflix red are the same
    // red, and two segments a reader cannot tell apart defeat the bar — so the
    // second one falls through to the rotation and stays distinguishable.
    const brand = brandColor(slice.symbol);
    if (brand && !claimedHexes.some((claimed) => tooClose(brand, claimed))) {
      claimedHexes.push(brand);
      return { fill: '', text: '', hex: brand };
    }
    return undefined;
  });

  let next = 0;
  return identities.map((color) => {
    if (color) return color;
    while (next < SLICE_PALETTE.length && used.has(SLICE_PALETTE[next].fill)) next += 1;
    // Past the rotation there is nothing honest left to say — the tail is
    // pooled long before this, so this only guards against a future longer bar.
    const picked = SLICE_PALETTE[next] ?? CASH_COLOR;
    used.add(picked.fill);
    return picked;
  });
}

/**
 * Slice key to its colour, for anything that renders a holding away from the
 * bar — the card's list of largest holdings, which has to match segment for
 * segment or the pairing it implies is a lie.
 */
export function allocationColorsByKey(
  slices: { key: string; symbol: string | null; asset_class: OwnershipAssetClass }[]
): Record<string, SliceColor> {
  const colors = allocationColors(slices);
  const byKey: Record<string, SliceColor> = {};
  slices.forEach((slice, index) => {
    if (slice.key) byKey[slice.key] = colors[index];
  });
  return byKey;
}

export const ASSET_CLASS_LABEL: Record<OwnershipAssetClass, string> = {
  equity: 'Equity',
  crypto: 'Crypto',
  gold: 'Gold',
  cash: 'Cash',
  fx_reserve: 'FX reserves',
  bond: 'Bonds',
  fund: 'Funds',
  other: 'Other',
};

/**
 * Badge tone per move kind. One map, because the strip, the card and the detail
 * list all render the same event and must not disagree about what it was.
 *
 * A transfer is neutral on purpose: coins leaving a wallet may be a sale, a
 * custody change or an internal shuffle, and the chain does not say which.
 * Colouring it red would publish a conclusion we cannot support.
 */
export const MOVE_BADGE: Record<OwnershipMoveKind, string> = {
  new: 'badge-bullish',
  add: 'badge-bullish',
  buy: 'badge-bullish',
  increase: 'badge-bullish',
  trim: 'badge-bearish',
  exit: 'badge-bearish',
  sell: 'badge-bearish',
  decrease: 'badge-bearish',
  transfer_in: 'badge-neutral',
  transfer_out: 'badge-neutral',
};

export const MOVE_LABEL: Record<OwnershipMoveKind, string> = {
  new: 'NEW',
  add: 'ADD',
  trim: 'TRIM',
  exit: 'EXIT',
  buy: 'BUY',
  sell: 'SELL',
  transfer_in: 'IN',
  transfer_out: 'OUT',
  increase: 'ADD',
  decrease: 'CUT',
};

export const CATEGORY_LABEL: Record<OwnershipCategory, string> = {
  institution: 'Investors',
  treasury: 'Companies',
  politician: 'Politicians',
  central_bank: 'Central Banks',
  onchain: 'Wallets',
};

/** Order the category chips appear in. Stable regardless of what has data. */
export const CATEGORY_ORDER: OwnershipCategory[] = [
  'institution',
  'treasury',
  'politician',
  'central_bank',
  'onchain',
];

/** Two-letter ISO country code to its flag emoji, or null for anything else. */
export function countryFlag(code: string | null | undefined): string | null {
  if (!code || code.length !== 2) return null;
  const upper = code.toUpperCase();
  if (!/^[A-Z]{2}$/.test(upper)) return null;
  // Indexed rather than spread: the tsconfig target predates iterable strings.
  return String.fromCodePoint(
    0x1f1e6 + upper.charCodeAt(0) - 65,
    0x1f1e6 + upper.charCodeAt(1) - 65
  );
}

/** Initials for an entity with no logo, e.g. "Trump Media…" -> "TM". */
export function monogram(name: string): string {
  return name
    .split(/\s+/)
    .filter((word) => /[A-Za-z0-9]/.test(word[0] ?? ''))
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join('');
}
