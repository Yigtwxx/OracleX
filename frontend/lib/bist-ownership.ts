/**
 * Pure derivations for the BIST ownership board and the company-page panel.
 *
 * Kept out of the components for the reason the rest of `lib/` is: what is
 * pinned here is the handful of places where "no answer" and "zero" are
 * different things — a holder with no market cap has a stake and no value, a
 * company with no named holder is not a company nobody owns — and a
 * component that computed them inline would be tested by nobody.
 */

import { formatPercent } from '@/lib/bist-format';
import { formatDate } from '@/lib/bist-format';
import type {
  BistAssetOwners,
  BistHolderCategory,
  BistOwnershipEntity,
  BistOwnershipFacts,
  BistOwnershipSlice,
  BistOwnershipStance,
  BistStakeMoveKind,
} from '@/lib/bist-api';

export const CATEGORY_LABEL: Record<BistHolderCategory, string> = {
  state: 'Kamu',
  holding: 'Holding',
  foreign: 'Yabancı ortak',
  fund: 'Fon',
  other: 'Diğer',
};

/** Display order of the category filter. The state first: it is the largest holder on the index. */
export const CATEGORY_ORDER: BistHolderCategory[] = [
  'state',
  'holding',
  'foreign',
  'fund',
  'other',
];

export function isHolderCategory(value: string | null | undefined): value is BistHolderCategory {
  return value !== null && value !== undefined && value in CATEGORY_LABEL;
}

export function filterByCategory(
  entities: BistOwnershipEntity[],
  category: BistHolderCategory | null
): BistOwnershipEntity[] {
  if (category === null) return entities;
  return entities.filter((entity) => entity.category === category);
}

/** The pooled tail slice the server appends past the named holdings. */
export const POOLED_SLICE_KEY = '__other__';

export interface OwnerSegment {
  key: string;
  label: string;
  ticker: string | null;
  pct: number;
  /** A CSS colour expression. The pooled tail is always the muted one. */
  color: string;
  pooled: boolean;
}

/**
 * One colour per ticker, the same on every card.
 *
 * Derived from the ticker rather than from the slice's position, so THYAO is
 * the same hue on the Varlık Fonu card, the QNB fund card and the rail — a
 * reader scanning the grid can spot a company by colour before reading it.
 * A position-based palette made every first slice purple, which told the
 * reader nothing except which holding was largest, and that is already the
 * first row of the list beneath.
 *
 * The hash is FNV-1a over the code, spread across the hue wheel with a fixed
 * saturation and lightness that clear the dark surface and stay legible on
 * the light theme. Collisions between two tickers are possible and tolerable:
 * the legend names them, and two hues 20° apart on one bar are still two.
 */
export function tickerColor(ticker: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < ticker.length; i++) {
    hash ^= ticker.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  // Golden-angle spreading keeps neighbouring hashes far apart on the wheel,
  // and a second byte of the hash picks one of three lightness steps, so two
  // tickers that land on the same hue still differ visibly side by side.
  const hue = Math.round(((hash % 360) * 137.508) % 360);
  const lightness = [54, 62, 70][(hash >>> 9) % 3];
  return `hsl(${hue} 68% ${lightness}%)`;
}

export function allocationSegments(slices: BistOwnershipSlice[]): OwnerSegment[] {
  return slices
    .filter((slice) => slice.pct > 0)
    .map((slice) => {
      const pooled = slice.key === POOLED_SLICE_KEY;
      const color = pooled ? 'var(--fg-subtle)' : tickerColor(slice.ticker ?? slice.key);
      return {
        key: slice.key,
        label: slice.label,
        ticker: slice.ticker,
        pct: slice.pct,
        color,
        pooled,
      };
    });
}

/** One sentence for a screen reader, in place of a title per segment. */
export function allocationSummary(segments: OwnerSegment[]): string {
  if (segments.length === 0) return 'Değerlenebilen pozisyon yok';
  return segments
    .map((segment) => `${segment.label} ${formatPercent(segment.pct, segment.pct < 0.1 ? 1 : 0)}`)
    .join(', ');
}

export interface HolderCoverage {
  /** Sum of every named ≥5% stake, as a fraction of capital. */
  namedPct: number;
  /** What is left — the free float and every holder under the threshold. */
  otherPct: number;
  /** How many of the named holders the board tracks. */
  tracked: number;
  untracked: number;
}

/**
 * What the shareholder table accounts for.
 *
 * `otherPct` is derived rather than read from the card so it always agrees
 * with the rows beside it; a table listing 49% and a bucket saying 60% would
 * be the kind of arithmetic a reader checks and then stops trusting.
 */
export function holderCoverage(owners: Pick<BistAssetOwners, 'holders'>): HolderCoverage {
  const namedPct = owners.holders.reduce((sum, holder) => sum + holder.stake_pct, 0);
  const tracked = owners.holders.filter((holder) => holder.tracked).length;
  return {
    namedPct,
    otherPct: Math.max(0, 1 - namedPct),
    tracked,
    untracked: owners.holders.length - tracked,
  };
}

/**
 * What the company's page says about its ownership in one line.
 *
 * Three sentences, because they are three facts: nobody crosses the
 * disclosure threshold, one holder controls the company outright, or the
 * capital is split between named holders.
 */
export function holderHeadline(owners: Pick<BistAssetOwners, 'holders'>): string {
  if (owners.holders.length === 0) {
    return '%5 eşiğini geçen ortak yok; sermayenin tamamı halka açık ve küçük paylardan oluşuyor.';
  }
  const largest = owners.holders[0];
  if (largest.stake_pct > 0.5) {
    return `${largest.label} ${formatPercent(largest.stake_pct)} ile çoğunluk ortağı.`;
  }
  const { namedPct } = holderCoverage(owners);
  return `${owners.holders.length} ortak sermayenin ${formatPercent(namedPct)}'ini tutuyor; en büyüğü ${largest.label} (${formatPercent(largest.stake_pct)}).`;
}

export interface BoardSummary {
  entities: number;
  withData: number;
  /** Sum of every entity's known lira value. `null` when nothing was valued. */
  totalValued: number | null;
  /** How many cards came back, over how many were asked for. */
  coverage: string;
}

export function boardSummary(board: {
  entities: BistOwnershipEntity[];
  tickers_covered: number;
  tickers_total: number;
  universe: string;
}): BoardSummary {
  const withData = board.entities.filter((entity) => entity.has_data);
  const valued = withData
    .map((entity) => entity.total_value_try)
    .filter((v): v is number => v !== null);
  return {
    entities: board.entities.length,
    withData: withData.length,
    totalValued: valued.length ? valued.reduce((sum, v) => sum + v, 0) : null,
    coverage: `${board.tickers_covered}/${board.tickers_total} ${board.universe}`,
  };
}

/** The Turkish word for how a lira value was arrived at. */
export const VALUE_BASIS_LABEL = {
  marked: 'piyasa değeriyle',
  reported: 'raporlanan',
  unknown: 'değerlenemedi',
} as const;

export const STAKE_MOVE_LABEL: Record<BistStakeMoveKind, string> = {
  new: 'Giriş',
  exit: 'Çıkış',
  add: 'Artış',
  trim: 'Azalış',
};

/**
 * When a holder came in, as far as the snapshots can tell.
 *
 * Three sentences for three states of knowledge: no snapshot has seen the
 * holder yet; the holder was already there on the first snapshot, so the
 * entry predates what is known; or the holder appeared on a later day, which
 * is the only case the word "giriş" is used for. Printing the baseline day as
 * an entry date would make every holder on the index look like it arrived
 * the day this feature shipped.
 */
export function sinceLabel(since: string | null, atBaseline: boolean): string {
  if (since === null) return 'Kayıt yok';
  if (atBaseline) return `≤ ${formatDate(since)}`;
  return `Giriş ${formatDate(since)}`;
}

/**
 * A stake change in points of capital, signed, or what stands in for one.
 *
 * `null` is "unknown" (one snapshot, nothing to compare) and is printed as a
 * dash; `0` is "unchanged" and is printed as such. The two must not share a
 * glyph: on the day after the first snapshot every row is genuinely
 * unchanged, and a dash there would read as the feature not working.
 */
export function formatStakeDelta(delta: number | null): string {
  if (delta === null) return '—';
  if (Math.abs(delta) < 0.0001) return '0';
  const points = delta * 100;
  const sign = points > 0 ? '+' : '';
  return `${sign}${points.toFixed(Math.abs(points) < 1 ? 2 : 1)} puan`;
}

export const OWNERSHIP_STANCE_LABEL: Record<BistOwnershipStance, string> = {
  state_anchored: 'Endeksin çapası kamu',
  family_holdings: 'Endeksin çapası holdingler',
  foreign_strategic: 'Endeksin çapası yabancı stratejik ortaklar',
  dispersed: 'Sahiplik dağınık',
};

export const OWNERSHIP_STANCE_TONE: Record<BistOwnershipStance, string> = {
  state_anchored: 'text-fg',
  family_holdings: 'text-fg',
  foreign_strategic: 'text-fg',
  dispersed: 'text-fg-muted',
};

export interface OwnershipChip {
  text: string;
  title: string;
}

/**
 * The three or four readings that decided the stance, as compact chips beside
 * it. Rendered from the facts alone, like the prompt, so the chips and the
 * paragraph can never disagree about a figure.
 */
export function ownershipChips(facts: BistOwnershipFacts): OwnershipChip[] {
  const chips: OwnershipChip[] = [];
  const [first, second] = facts.total.categories;
  if (first && first.share_pct !== null) {
    chips.push({
      title: 'Değerlenen toplamın en büyük iki ortak türüne düşen payı',
      text:
        `${CATEGORY_LABEL[first.category].toLocaleLowerCase('tr')} %${first.share_pct}` +
        (second && second.share_pct !== null
          ? ` · ${CATEGORY_LABEL[second.category].toLocaleLowerCase('tr')} %${second.share_pct}`
          : ''),
    });
  }
  if (facts.holders.top3_share_pct !== null) {
    chips.push({
      title: 'En büyük üç ortağın değerlenen toplamdaki payı',
      text: `ilk 3 ortak %${facts.holders.top3_share_pct}`,
    });
  }
  if (facts.companies.median_named_stake_pct !== null) {
    chips.push({
      title: 'Medyan şirkette %5 üzeri ortakların tuttuğu toplam pay',
      text: `medyan sahiplik %${facts.companies.median_named_stake_pct}`,
    });
  }
  if (facts.companies.median_foreign_ratio_pct !== null) {
    chips.push({
      title: 'Halka açık kısımdaki yabancı payı, XU100 medyanı',
      text: `yabancı medyan %${facts.companies.median_foreign_ratio_pct}`,
    });
  }
  chips.push({
    title: 'Şirketlerden kaçında bir ortak sermayenin yarısından fazlasını tutuyor',
    text: `${facts.companies.majority_held} şirkette çoğunluk ortağı`,
  });
  return chips;
}
