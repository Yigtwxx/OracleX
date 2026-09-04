/**
 * Every branch on the Halka Arz board.
 *
 * Same reason as `bist-financials`: vitest collects `lib/**` only, so a
 * conditional inside a panel is a conditional nobody runs twice.
 *
 * The rule this file protects is narrower than the Bilanço board's and just as
 * consequential. An offering whose return could not be measured must be
 * *excluded and counted*, never drawn at zero. A bar at zero on a returns chart
 * reads as a listing that went nowhere, which is a statement about a company we
 * have no basis for.
 */

import type { FundAllocationSegment } from '@/lib/fund-allocation';
import type { Ipo, IpoProceedsLine, IpoResults, IpoState, IpoStructure } from '@/lib/bist-api';

export type IpoBasis = 'real' | 'nominal';

/** Board windows, in months. `0` means everything the calendar carries. */
export type IpoWindow = 12 | 24 | 60 | 0;

export const WINDOW_OPTIONS: Array<{ value: IpoWindow; label: string }> = [
  { value: 12, label: '12 ay' },
  { value: 24, label: '24 ay' },
  { value: 60, label: '5 yıl' },
  { value: 0, label: 'Tümü' },
];

/**
 * Fixed bucket edges, in fraction terms.
 *
 * Fixed rather than derived from the data, because a histogram whose buckets
 * move with the sample cannot be compared between two windows — and comparing
 * windows is most of what this panel is for.
 */
export const BUCKET_EDGES = [-0.5, -0.25, 0, 0.25, 0.5, 1] as const;

export const BUCKET_LABELS = [
  '< -%50',
  '-%50 … -%25',
  '-%25 … 0',
  '0 … +%25',
  '+%25 … +%50',
  '+%50 … +%100',
  '> +%100',
] as const;

/** Measured listings needed before a distribution is drawn at all. */
export const MIN_SAMPLE = 8;

export interface RankRow {
  slug: string;
  ticker: string | null;
  company: string;
  value: number;
  price: number | null;
  listingDate: string | null;
  daysListed: number;
  seasoned: boolean;
}

export interface Bucket {
  label: string;
  count: number;
}

const STATE_LABELS: Record<IpoState, string> = {
  undated: 'Tarih belli değil',
  upcoming: 'Yaklaşan',
  book_open: 'Talep toplanıyor',
  listed: 'İşlem görüyor',
};

export function ipoStateLabel(state: IpoState): string {
  return STATE_LABELS[state] ?? state;
}

function measured(row: Ipo, basis: IpoBasis): number | null {
  const performance = row.performance;
  if (!performance) return null;
  const value = basis === 'real' ? performance.real : performance.nominal;
  return value ?? null;
}

/**
 * Measured listings, best first.
 *
 * Rows with no performance block, and rows with no figure in the chosen frame,
 * are dropped. `unmeasuredCount` accounts for exactly those, and the panel
 * prints both numbers so a reader can see what is not on the chart.
 */
export function rankByReturn(rows: Ipo[], basis: IpoBasis): RankRow[] {
  return rows
    .map((row) => ({ row, value: measured(row, basis) }))
    .filter((entry): entry is { row: Ipo; value: number } => entry.value !== null)
    .map(({ row, value }) => ({
      slug: row.slug,
      ticker: row.ticker,
      company: row.company,
      value,
      price: row.price?.low ?? null,
      listingDate: row.listing_date,
      daysListed: row.performance!.days_listed,
      seasoned: row.performance!.seasoned,
    }))
    .sort((a, b) => b.value - a.value);
}

export function unmeasuredCount(rows: Ipo[], basis: IpoBasis): number {
  return rows.filter((row) => measured(row, basis) === null).length;
}

export function medianReturn(rows: Ipo[], basis: IpoBasis): number | null {
  const values = rows
    .map((row) => measured(row, basis))
    .filter((value): value is number => value !== null)
    .sort((a, b) => a - b);
  if (values.length === 0) return null;
  const middle = Math.floor(values.length / 2);
  return values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

export function positiveShare(rows: Ipo[], basis: IpoBasis): number | null {
  const values = rows
    .map((row) => measured(row, basis))
    .filter((value): value is number => value !== null);
  if (values.length === 0) return null;
  return values.filter((value) => value > 0).length / values.length;
}

/**
 * The distribution, in fixed buckets.
 *
 * A value sitting exactly on an edge falls in the *lower* bucket, so 0 counts
 * as "did not make money". The off-by-one here silently moves the answer to the
 * only question this panel asks, which is why the boundaries are pinned in the
 * tests rather than left to whichever comparison was typed first.
 */
export function returnBuckets(rows: Ipo[], basis: IpoBasis): Bucket[] {
  const counts = BUCKET_LABELS.map((label) => ({ label, count: 0 }));
  for (const row of rows) {
    const value = measured(row, basis);
    if (value === null) continue;
    let index = 0;
    while (index < BUCKET_EDGES.length && value > BUCKET_EDGES[index]) index += 1;
    counts[index].count += 1;
  }
  return counts;
}

export function histogramReady(rows: Ipo[], basis: IpoBasis): boolean {
  return rows.filter((row) => measured(row, basis) !== null).length >= MIN_SAMPLE;
}

export interface CalendarLane {
  month: string;
  entries: Ipo[];
}

/**
 * Upcoming offerings, grouped by the month their book opens.
 *
 * Grouped on the start, so a book spanning a month boundary appears once, where
 * a reader would look for it. Undated rows are excluded here and returned by
 * `undatedRows` instead — placing them on a guessed month is the one thing this
 * board must not do.
 */
export function calendarLanes(rows: Ipo[]): CalendarLane[] {
  const byMonth = new Map<string, Ipo[]>();
  for (const row of rows) {
    if (!row.offer_dates) continue;
    const month = row.offer_dates.start.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, []);
    byMonth.get(month)!.push(row);
  }
  return Array.from(byMonth.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([month, entries]) => ({
      month,
      entries: entries.sort((a, b) =>
        (a.offer_dates?.start ?? '').localeCompare(b.offer_dates?.start ?? '')
      ),
    }));
}

export function undatedRows(rows: Ipo[]): Ipo[] {
  return rows.filter((row) => !row.offer_dates);
}

const GROUP_COLORS: Record<string, string> = {
  domestic_retail: 'var(--oi-venue-1)',
  domestic_institutional: 'var(--oi-total)',
  foreign_retail: 'var(--oi-price)',
  foreign_institutional: 'var(--oi-venue-3)',
  other: 'var(--fg-subtle)',
};

/**
 * Who got the shares, as bar segments.
 *
 * Shares are passed through unnormalised. The calendar rounds and its groups
 * can sum to 0.98; `FundAllocationBar` leaves the remainder as bare track,
 * which is the honest rendering of a filing that does not quite add up.
 */
export function allocationSegments(
  results: IpoResults | null
): { segments: FundAllocationSegment[]; total: number } | null {
  if (!results || results.groups.length === 0) return null;
  const usable = results.groups.filter((group) => group.share !== null);
  if (usable.length === 0) return null;
  return {
    segments: usable.map((group) => ({
      key: group.key,
      label: group.label,
      weight: group.share as number,
      color: GROUP_COLORS[group.key] ?? GROUP_COLORS.other,
    })),
    total: usable.reduce((sum, group) => sum + (group.share as number), 0),
  };
}

/**
 * New capital against existing shareholders selling.
 *
 * The most interpretively loaded number on the board: one puts money into the
 * company, the other puts it into a seller's pocket. A zero-lot side yields one
 * full-width segment rather than a zero-width second one, which would render as
 * a hairline a reader could misread as a sliver of the other kind.
 */
export function structureSegments(
  structure: IpoStructure | null
): { segments: FundAllocationSegment[]; total: number } | null {
  if (!structure) return null;
  const increase = structure.capital_increase_lots ?? 0;
  const sale = structure.share_sale_lots ?? 0;
  const total = increase + sale;
  if (total <= 0) return null;

  const parts: FundAllocationSegment[] = [];
  if (increase > 0) {
    parts.push({
      key: 'capital_increase',
      label: 'Sermaye artırımı',
      weight: increase / total,
      color: 'var(--up)',
    });
  }
  if (sale > 0) {
    parts.push({
      key: 'share_sale',
      label: 'Ortak satışı',
      weight: sale / total,
      color: 'var(--oi-price)',
    });
  }
  return { segments: parts, total: 1 };
}

/**
 * What the prospectus says the money is for.
 *
 * Document order is preserved rather than sorted by size: the order is the
 * company's own stated priority, and re-ranking it would be editorialising a
 * filing.
 */
export function proceedsSegments(
  lines: IpoProceedsLine[] | null
): { segments: FundAllocationSegment[]; total: number } | null {
  if (!lines || lines.length === 0) return null;
  const usable = lines.filter((line) => line.share !== null);
  if (usable.length === 0) return null;
  return {
    segments: usable.map((line, index) => ({
      key: `proceeds-${index}`,
      label: line.label,
      weight: line.share as number,
      color: `var(--heat-seq-${(index % 4) + 1})`,
    })),
    total: usable.reduce((sum, line) => sum + (line.share as number), 0),
  };
}

export type AbsentBlock = 'results' | 'structure' | 'proceeds' | 'performance';

/**
 * Why one block on a row is empty.
 *
 * Four different facts get four different sentences. "Not listed yet" and
 * "results not published" and "no code assigned" are distinct situations, and
 * collapsing them into one apology is how a board stops being informative about
 * its own gaps.
 */
export function absentCopy(row: Ipo, block: AbsentBlock): string {
  if (block === 'results') {
    return row.state === 'listed'
      ? 'Halka arz sonuçları bu sayfada henüz yayımlanmadı.'
      : 'Talep toplama tamamlanmadığı için dağıtım sonuçları yok.';
  }
  if (block === 'structure') {
    return 'Arz şekli (sermaye artırımı / ortak satışı) bu sayfada yayımlanmamış.';
  }
  if (block === 'proceeds') {
    return 'İzahnamede belirtilen fon kullanım dağılımı bu sayfada yer almıyor.';
  }
  if (!row.ticker) {
    return 'Şirkete henüz BIST kodu atanmadı, bu yüzden getiri ölçülemiyor.';
  }
  if (row.state !== 'listed') {
    return 'Pay henüz işlem görmüyor.';
  }
  if (row.price?.is_band) {
    return 'Arz fiyatı bir aralık olarak açıklanmış ve kesinleşen fiyat bu sayfada yok; aralığın ortası uydurma bir sayı olurdu.';
  }
  if (row.unparsed.includes('detail')) {
    return 'Bu arzın detay sayfası okunamadı.';
  }
  return 'Getiriyi ölçmek için gereken veriler eksik.';
}
