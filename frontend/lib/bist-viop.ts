/**
 * The derivations the VİOP panels share.
 *
 * Four panels read the same contract list and ask four different questions of
 * it. Putting the arithmetic here rather than in each panel is what keeps the
 * KPI strip and the charts from disagreeing: the "42 contracts opening" in the
 * strip and the filled points on the scatter are the same predicate evaluated
 * once, not two similar filters written a fortnight apart.
 *
 * It also puts the logic where the test runner can see it. `vitest.config.mts`
 * only collects `lib/**\/*.test.ts`, so a rule that lives in a component is a
 * rule nothing checks.
 *
 * Two conventions carry through the file. Every ratio derived here is a
 * **fraction** — `0.05` is five percent — because that is what `/api/bist/*`
 * sends and what `bist-format` formats from. The `BistViopFacts` figures are
 * the exception and go through `formatPoints`; they arrive already bucketed
 * into percentage points, for the reason `lib/bist-market-note.ts` records at
 * length. And open interest that was never published stays `null` rather than
 * collapsing to zero: "the column was empty" and "nobody holds this" look
 * identical once both are numbers, and only one of them is something the board
 * actually said.
 */

import type {
  BistViopFacts,
  BistViopMapFacts,
  BistViopMapStance,
  BistViopStance,
  ViopContract,
} from './bist-api';
import { EMPTY, formatCompact, formatNumber } from './bist-format';
import { type Chip, formatPoints } from './bist-market-note';
import type { Quadrant } from './bist-positioning';

export type { Quadrant };

/**
 * The futures on the board, without the options listed beside them.
 *
 * Roughly a fifth of the rows are calls and puts, and every panel on this page
 * is a futures read. `ISCTR (30 Eyl 26) Satim opsiyonu` settles at 0.13 against
 * the future's 13.16, because one figure is a premium and the other is a price:
 * summed they add two unrelated books into one open-interest total, and placed
 * on one axis they draw a term structure in 99% backwardation.
 *
 * Applied once at the page rather than inside each panel, so the strip of tiles
 * and the four charts can never end up counting different boards.
 */
export function futuresOnly(contracts: ViopContract[]): ViopContract[] {
  return contracts.filter((contract) => contract.kind === 'future');
}

/**
 * Which positioning quadrant a contract sits in, or null if it sits on an axis.
 *
 * Mirrors `quadrant_of` in `backend/services/bist/viop_note.py`, deliberately:
 * the scatter and the paragraph above it must count the same contracts, and a
 * second definition written a fortnight later is how they stop doing that.
 *
 * Exactly zero on either axis is the absence of a read rather than a weak one.
 * Open interest that did not move says nothing about who opened what, and
 * rounding it into the nearest quadrant would invent a direction the market did
 * not express.
 */
export function viopQuadrantOf(contract: ViopContract): Quadrant | null {
  const oi = contract.open_interest_change;
  const price = contract.change_pct;
  if (oi === null || price === null || oi === 0 || price === 0) return null;
  if (oi > 0) return price > 0 ? 'long_build' : 'short_build';
  return price > 0 ? 'short_cover' : 'long_liquidation';
}

/**
 * A contract's open-interest change against *yesterday's* book.
 *
 * Dividing by today's total would already contain the move, understating a
 * build and overstating a liquidation — a book that doubled overnight reads as
 * +50% on today's denominator.
 */
export function oiChangeRatio(contract: ViopContract): number | null {
  const { open_interest: oi, open_interest_change: change } = contract;
  if (oi === null || change === null) return null;
  const previous = oi - change;
  return previous > 0 ? change / previous : null;
}

// ── Open interest by underlying ────────────────────────────────────────────

export interface UnderlyingBar {
  underlying: string;
  /** Null when no expiry published a figure. Not the same as an empty book. */
  openInterest: number | null;
  openInterestChange: number | null;
  /** Change against yesterday, as a fraction. */
  changeRatio: number | null;
  /** How many expiries are listed on this name. */
  expiries: number;
  /** Share of everything measured on the board, as a fraction. */
  share: number | null;
}

/**
 * Every contract folded onto its underlying, largest book first.
 *
 * Summed across expiries rather than shown per contract, for the reason
 * `roll_by_underlying` records in Python: a reader asking "how big is the
 * USDTRY position" means across every expiry, and the near month alone
 * understates it by roughly half.
 *
 * Built from the contract list rather than from the payload's `summary`, which
 * flattens an unpublished figure back to `0.0` for payload-compatibility
 * reasons of its own. A bar drawn from that would state that nobody holds a
 * name whose column simply came back empty.
 */
export function underlyingBars(contracts: ViopContract[], limit?: number): UnderlyingBar[] {
  const expiries = new Map<string, number>();
  const interest = new Map<string, number>();
  const change = new Map<string, number>();

  for (const contract of contracts) {
    const key = contract.underlying;
    expiries.set(key, (expiries.get(key) ?? 0) + 1);
    // Summed independently: a row can publish one and not the other, and
    // pairing them would drop a reading that is there.
    if (contract.open_interest !== null) {
      interest.set(key, (interest.get(key) ?? 0) + contract.open_interest);
    }
    if (contract.open_interest_change !== null) {
      change.set(key, (change.get(key) ?? 0) + contract.open_interest_change);
    }
  }

  let total = 0;
  // `forEach` rather than iterating the Map: the build targets ES5 without
  // `downlevelIteration`, so spreading an iterator is a compile error here.
  interest.forEach((value) => {
    total += value;
  });

  const bars: UnderlyingBar[] = [];
  expiries.forEach((count, underlying) => {
    const openInterest = interest.has(underlying) ? (interest.get(underlying) as number) : null;
    const openInterestChange = change.has(underlying) ? (change.get(underlying) as number) : null;
    const previous =
      openInterest !== null && openInterestChange !== null ? openInterest - openInterestChange : 0;

    bars.push({
      underlying,
      openInterest,
      openInterestChange,
      changeRatio:
        openInterestChange !== null && previous > 0 ? openInterestChange / previous : null,
      expiries: count,
      share: openInterest !== null && total > 0 ? openInterest / total : null,
    });
  });

  bars.sort((a, b) => (b.openInterest ?? -1) - (a.openInterest ?? -1));
  return limit === undefined ? bars : bars.slice(0, limit);
}

export interface BoardTotals {
  /** Summed across every contract that published a figure. */
  openInterest: number;
  change: number;
  /** Against yesterday's book, as a fraction. Null when yesterday cannot be derived. */
  changeRatio: number | null;
  /** Contracts publishing an open-interest figure, and those publishing none. */
  measured: number;
  silent: number;
}

/**
 * The board's own totals, from the contracts rather than from the payload.
 *
 * `summary.total_open_interest` answers the first of these and the endpoint has
 * published it as a number since it existed, but it cannot answer the last two:
 * it flattens an unpublished column back to zero, so a board where a third of
 * the rows came back empty is indistinguishable from one where they are all
 * quiet. The strip states both, because a total the reader is comparing to
 * yesterday's deserves to say how much of the board it covers.
 */
export function boardTotals(contracts: ViopContract[]): BoardTotals {
  let openInterest = 0;
  let change = 0;
  let measured = 0;

  for (const contract of contracts) {
    if (contract.open_interest !== null) {
      openInterest += contract.open_interest;
      measured += 1;
    }
    if (contract.open_interest_change !== null) change += contract.open_interest_change;
  }

  const previous = openInterest - change;
  return {
    openInterest,
    change,
    changeRatio: previous > 0 ? change / previous : null,
    measured,
    silent: contracts.length - measured,
  };
}

// ── The positioning scatter ────────────────────────────────────────────────

export interface ViopQuadrantPoint {
  contract: string;
  underlying: string;
  expiry: string;
  quadrant: Quadrant;
  openInterest: number;
  openInterestChange: number;
  /** Against yesterday's book, as a fraction. */
  changeRatio: number;
  changePct: number;
}

/**
 * The contracts that can be placed in a quadrant at all.
 *
 * A point needs four readings — a book, a change in it, a ratio to place it on
 * the axis and a price move — and a contract missing any of them is dropped
 * rather than pinned to zero. Half the board is normally dropped here, which is
 * why the panel states how many contracts it drew.
 */
export function quadrantPoints(contracts: ViopContract[]): ViopQuadrantPoint[] {
  const points: ViopQuadrantPoint[] = [];

  for (const contract of contracts) {
    const quadrant = viopQuadrantOf(contract);
    const ratio = oiChangeRatio(contract);
    if (
      quadrant === null ||
      ratio === null ||
      contract.open_interest === null ||
      contract.open_interest_change === null ||
      contract.change_pct === null
    ) {
      continue;
    }

    points.push({
      contract: contract.contract,
      underlying: contract.underlying,
      expiry: contract.expiry,
      quadrant,
      openInterest: contract.open_interest,
      openInterestChange: contract.open_interest_change,
      changeRatio: ratio,
      changePct: contract.change_pct,
    });
  }

  return points;
}

/** How many contracts sit in each quadrant. */
export function quadrantCounts(points: ViopQuadrantPoint[]): Record<Quadrant, number> {
  const counts: Record<Quadrant, number> = {
    long_build: 0,
    short_build: 0,
    short_cover: 0,
    long_liquidation: 0,
  };
  for (const point of points) counts[point.quadrant] += 1;
  return counts;
}

// ── Term structure ─────────────────────────────────────────────────────────

export interface TermPoint {
  expiry: string;
  expiryDate: string;
  settlement: number;
  openInterest: number | null;
  /** Against the front month's settlement, as a fraction. Zero at the front. */
  basis: number;
}

/**
 * One underlying's strip, front month first.
 *
 * **Settlement rather than last, and the two are not interchangeable.** The far
 * months on this board can go a whole session without a trade, so their last
 * price is whenever somebody last dealt — which puts a stale October print
 * beside a live August one and draws a curve out of the gap between two
 * different moments. The settlement price is published for every contract every
 * day, which is the only thing that makes two points comparable.
 *
 * Ordered by `expiry_date` and never by the label: `31 Ağu 26` and `30 Eki 26`
 * sort alphabetically with October first, which inverts the curve.
 */
export function termCurve(contracts: ViopContract[], underlying: string): TermPoint[] {
  const dated = contracts
    .filter(
      (contract) =>
        contract.underlying === underlying &&
        contract.expiry_date !== null &&
        contract.settlement !== null &&
        contract.settlement !== 0
    )
    .sort((a, b) => (a.expiry_date as string).localeCompare(b.expiry_date as string));

  if (dated.length === 0) return [];
  const front = dated[0].settlement as number;

  return dated.map((contract) => ({
    expiry: contract.expiry,
    expiryDate: contract.expiry_date as string,
    settlement: contract.settlement as number,
    openInterest: contract.open_interest,
    basis: ((contract.settlement as number) - front) / front,
  }));
}

/** Whether a strip prices its back month above, below or level with its front. */
export type CurveShape = 'contango' | 'backwardation' | 'flat';

/**
 * Mirrors `FLAT_SPREAD_PCT` in `backend/services/bist/viop_note.py`. Two points
 * differing by a quarter of a percent are the same price quoted twice.
 */
export const FLAT_SPREAD = 0.005;

/**
 * The shape of a strip.
 *
 * Deliberately not read as sentiment. Turkish rates make the cost of carry
 * large, so a strip settling above its front month is arithmetic and carries no
 * information at all; `flat` and `backwardation` are the readings worth a
 * label, which is why the deadband exists rather than a sign test.
 */
export function curveShape(points: TermPoint[]): CurveShape | null {
  if (points.length < 2) return null;
  const spread = points[points.length - 1].basis;
  if (spread >= FLAT_SPREAD) return 'contango';
  if (spread <= -FLAT_SPREAD) return 'backwardation';
  return 'flat';
}

export const CURVE_SHAPE_LABEL: Record<CurveShape, string> = {
  contango: 'Contango',
  backwardation: 'Backwardation',
  flat: 'Düz',
};

export const CURVE_SHAPE_NOTE: Record<CurveShape, string> = {
  // Named as the resting state rather than as a signal: with rates this high a
  // strip above spot is the cost of carry, and reading it as optimism is the
  // single most common misreading of a Turkish futures curve.
  contango: 'Uzak vadeler yakın vadenin üzerinde — yüksek faizde olağan taşıma maliyeti.',
  backwardation: 'Uzak vadeler yakın vadenin altında — taşıma maliyetinin tersi, asıl bulgu bu.',
  flat: 'Vadeler arasında anlamlı fark yok.',
};

// ── The split across expiries ──────────────────────────────────────────────

/** Everything outside the named underlyings, gathered into one band. */
export const OTHER_KEY = 'Diğer';

export interface ExpiryStack {
  expiryDate: string;
  label: string;
  total: number;
  /** Open interest per underlying, in the order `keys` gives. */
  byUnderlying: Record<string, number>;
}

const MONTHS_TR = [
  'Oca',
  'Şub',
  'Mar',
  'Nis',
  'May',
  'Haz',
  'Tem',
  'Ağu',
  'Eyl',
  'Eki',
  'Kas',
  'Ara',
];

/**
 * An ISO expiry day as the short label the axis wants: `2026-10-30` → `Eki 26`.
 *
 * Built from the string rather than through `Date`, which would apply the
 * viewer's timezone and move a contract expiring at midnight into the previous
 * month for anyone west of Istanbul.
 */
export function expiryLabel(iso: string): string {
  const [year, month] = iso.split('-');
  const index = Number(month) - 1;
  if (!Number.isInteger(index) || index < 0 || index > 11) return iso;
  return `${MONTHS_TR[index]} ${year.slice(2)}`;
}

/**
 * Open interest per expiry, split across the underlyings that carry it.
 *
 * The reading a table sorted by open interest cannot give: a front month
 * holding almost all of the book is a market that has not rolled yet, and the
 * same board a fortnight later at the same size is a different set of
 * positions. Undated contracts are excluded rather than bucketed into an
 * "unknown" column — they would sit at one end of a time axis and be read as an
 * expiry.
 */
export function expiryStacks(contracts: ViopContract[], keys: string[]): ExpiryStack[] {
  const wanted = new Set(keys);
  const byDate = new Map<string, ExpiryStack>();

  for (const contract of contracts) {
    const date = contract.expiry_date;
    if (date === null || contract.open_interest === null) continue;

    const stack = byDate.get(date) ?? {
      expiryDate: date,
      label: expiryLabel(date),
      total: 0,
      byUnderlying: {},
    };
    // Everything outside the named set is one bucket rather than fifty slivers
    // no legend could carry.
    const key = wanted.has(contract.underlying) ? contract.underlying : OTHER_KEY;
    stack.byUnderlying[key] = (stack.byUnderlying[key] ?? 0) + contract.open_interest;
    stack.total += contract.open_interest;
    byDate.set(date, stack);
  }

  const stacks: ExpiryStack[] = [];
  byDate.forEach((stack) => stacks.push(stack));
  return stacks.sort((a, b) => a.expiryDate.localeCompare(b.expiryDate));
}

/** Share of all dated open interest still sitting in the nearest expiry. */
export function frontShare(stacks: ExpiryStack[]): number | null {
  if (stacks.length === 0) return null;
  const total = stacks.reduce((sum, stack) => sum + stack.total, 0);
  return total > 0 ? stacks[0].total / total : null;
}

// ── The note header ────────────────────────────────────────────────────────

/**
 * The stance names the flow, not the price.
 *
 * "Yükseliş" would describe what the board did; the read is *who did it* — new
 * money arriving on one side looks nothing like the other side being squeezed
 * out, and both print the same green.
 */
export const VIOP_STANCE_LABEL: Record<BistViopStance, string> = {
  long_build: 'Yeni para uzun tarafta',
  short_build: 'Yeni para kısa tarafta',
  short_cover: 'Kısalar kapatıyor',
  long_liquidation: 'Uzunlar çıkıyor',
  mixed: 'Yön belirsiz',
};

/**
 * Tone follows the price direction, as it does everywhere else on this realm.
 *
 * Not whether the flow is healthy: a build and a short cover are opposite
 * events that both happen on a green day, and colouring one of them red because
 * it is the less durable of the two would state a view the header is not
 * entitled to.
 */
export const VIOP_STANCE_TONE: Record<BistViopStance, string> = {
  long_build: 'text-up',
  short_cover: 'text-up',
  short_build: 'text-down',
  long_liquidation: 'text-down',
  mixed: 'text-fg-muted',
};

/**
 * The readings worth a glance, in the order a desk reaches for them.
 *
 * Deliberately short. This is the line that survives when the model does not
 * answer, so it carries what the panels below genuinely cannot show — how much
 * of the day's movement the stance actually rests on, whether the board is one
 * contract, and how much of the book has not rolled — rather than a summary of
 * what is already on screen.
 */
export function viopChips(facts: BistViopFacts): Chip[] {
  const chips: Chip[] = [];
  const { board, concentration, quadrants, roll } = facts;

  if (board.total_open_interest !== null) {
    chips.push({
      title: 'Tahtadaki toplam açık pozisyon ve dünkü kitaba göre değişimi',
      text: `AP ${formatCompact(board.total_open_interest, 1)} ${formatPoints(board.growth_pct, { sign: true })}`,
    });
  }

  const weight = quadrants.weight_pct[facts.stance];
  if (weight != null) {
    chips.push({
      title: 'Günün açık pozisyon hareketinin bu kadranda toplanan payı',
      text: `hareketin ${formatPoints(weight)}'i`,
    });
  }

  const top = concentration.top[0];
  if (top && top.share_pct !== null) {
    chips.push({
      title: 'Tüm açık pozisyonun en büyük dayanakta toplanan payı',
      text: `${top.underlying} ${formatPoints(top.share_pct)}`,
    });
  }

  if (roll.front_share_pct !== null) {
    chips.push({
      title: 'Açık pozisyonun hâlâ en yakın vadede duran payı',
      text: `yakın vade ${formatPoints(roll.front_share_pct)}`,
    });
  }

  // Only when it is large enough to change how the rest of the line is read. An
  // empty open-interest column is an unread figure, not an empty book, and a
  // reader comparing totals is entitled to know how much of the board is
  // missing from them.
  if (board.silent > 0) {
    chips.push({
      title: 'Açık pozisyon sütunu boş gelen sözleşmeler — pozisyonsuz değil, okunamamış',
      text: `${board.silent}/${board.contracts} sözleşme AP yayımlamadı`,
    });
  }

  return chips;
}

// ── Teminat haritası ────────────────────────────────────────────────────────

/**
 * The lean names where the bands sit, not what price did.
 *
 * A long-heavy field is one whose surviving margin bands are below the spot
 * price; that is the reading, and "yükseliş" would claim something the map
 * does not know.
 */
export const VIOP_MAP_STANCE_LABEL: Record<BistViopMapStance, string> = {
  long_heavy: 'Kitap uzun tarafta ağır',
  short_heavy: 'Kitap kısa tarafta ağır',
  balanced: 'Kitap dengeli',
  empty: 'Ayakta pozisyon yok',
};

/** Tone follows the side, the way the map's own colours do. */
export const VIOP_MAP_STANCE_TONE: Record<BistViopMapStance, string> = {
  long_heavy: 'text-up',
  short_heavy: 'text-down',
  balanced: 'text-fg-muted',
  empty: 'text-fg-muted',
};

/**
 * The readings worth a glance above the field.
 *
 * What the picture cannot say: how much stands, which side it leans to, and
 * how far the nearest heavy band on each side is from the close — distances
 * are the whole point of a scan-range map and the one thing a colour ramp
 * never states. Not the scan range itself, which the toolbar already prints.
 */
export function viopMapChips(facts: BistViopMapFacts): Chip[] {
  const chips: Chip[] = [];
  const { book, levels, window } = facts;

  if (book.standing_try !== null && book.standing_try > 0) {
    chips.push({
      title: 'Henüz fiyatın içinden geçilmemiş bantlarda duran toplam nominal',
      text: `ayakta ${formatCompact(book.standing_try, 1)} ₺`,
    });
  }

  if (book.long_share_pct !== null) {
    chips.push({
      title: 'Ayakta duran nominalin uzun tarafa ait payı',
      text: `uzun payı ${formatPoints(book.long_share_pct)}`,
    });
  }

  const [nearestLong] = levels.long;
  if (nearestLong && nearestLong.distance_pct !== null) {
    chips.push({
      title: 'Uzun tarafın en ağır bandı ve son spot kapanışa uzaklığı',
      text: `uzun bant ${formatNumber(nearestLong.price, 2)} · ${formatPoints(nearestLong.distance_pct, { sign: true })}`,
    });
  }

  const [nearestShort] = levels.short;
  if (nearestShort && nearestShort.distance_pct !== null) {
    chips.push({
      title: 'Kısa tarafın en ağır bandı ve son spot kapanışa uzaklığı',
      text: `kısa bant ${formatNumber(nearestShort.price, 2)} · ${formatPoints(nearestShort.distance_pct, { sign: true })}`,
    });
  }

  // Only when it changes how the field reads. A session whose settlement did
  // not move placed nothing, and a reader comparing the two sides is entitled
  // to know how much of the window is missing from both.
  if (window.undirected_sessions > 0) {
    chips.push({
      title: 'Uzlaşma fiyatı değişmediği için hiçbir tarafa yazılamayan seanslar',
      text: `${window.undirected_sessions} seans yönsüz`,
    });
  }

  return chips;
}

/** A contract count as text, or the em dash every empty figure on this realm uses. */
export function formatCount(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? formatNumber(value, 0) : EMPTY;
}
