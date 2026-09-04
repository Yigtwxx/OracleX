/**
 * Every branch on the Bilanço board.
 *
 * `vitest.config.mts` collects `lib/**` and nothing else — there is no jsdom in
 * this repo and no component test — so a conditional inside a panel is a
 * conditional nobody ever runs twice. The components below this module are
 * presentational: they receive a series, a state or a copy string and render it.
 *
 * The rule this file exists to protect is the one the whole board rests on: a
 * figure that has not been restated into today's lira must never be drawn under
 * a "Reel" label. Everything else here is chart plumbing.
 */

import type {
  BistDeflation,
  BistDeflationReason,
  BistFinancials,
  BistQuarter,
} from '@/lib/bist-api';
import {
  EMPTY,
  formatCompactTry,
  formatPercent,
  formatSignedPercent,
  toneClass,
} from '@/lib/bist-format';

/** Which price frame the reader asked for. */
export type Basis = 'real' | 'nominal';

/**
 * Why a panel is empty, and the two reasons are not interchangeable.
 *
 * `absent_layout` means this kind of company has no such line — a bank has no
 * gross profit the way a factory does. `absent_unreported` means the line
 * exists and the company did not fill it in. A reader looking at a blank frame
 * is asking exactly which, and answering with one string for both is how a
 * board starts looking broken instead of honest.
 */
export type FieldState = 'present' | 'absent_layout' | 'absent_unreported';

export interface ChartPoint {
  period: string;
  value: number | null;
}

export interface FinancialSeries {
  field: string;
  label: string;
  points: ChartPoint[];
}

export interface Tile {
  label: string;
  value: string;
  note?: string;
  tone?: string;
  title?: string;
}

export const FIELD_LABELS: Record<string, string> = {
  revenue: 'Hasılat',
  gross_profit: 'Brüt kâr',
  operating_profit: 'Faaliyet kârı',
  ebitda: 'FAVÖK',
  net_income: 'Net kâr',
  financing_expense: 'Finansman gideri',
  ocf: 'Faaliyet nakit akışı',
  capex: 'Yatırım harcaması',
  fcf: 'Serbest nakit akışı',
  dividends_paid: 'Ödenen temettü',
  equity: 'Özkaynak',
  total_assets: 'Toplam varlık',
  total_debt: 'Toplam borç',
  short_term_debt: 'Kısa vadeli borç',
  cash: 'Nakit',
  current_assets: 'Dönen varlık',
  current_liabilities: 'Kısa vadeli yükümlülük',
};

const LAYOUT_LABELS: Record<string, string> = {
  industrial: 'sanayi/ticaret',
  bank: 'banka',
  insurance: 'sigorta',
};

const REASON_COPY: Record<BistDeflationReason, string> = {
  cpi_key_missing:
    'Enflasyon serisi bu kurulumda tanımlı değil, bu yüzden reel görünüm kapalı. Aşağıdaki her rakam nominal lira.',
  cpi_unavailable:
    'TCMB fiyat endeksine şu anda ulaşılamıyor, bu yüzden reel görünüm kapalı. Aşağıdaki her rakam nominal lira.',
  cpi_too_short:
    'Fiyat endeksi bu şirketin en yeni çeyreğine ulaşmıyor, bu yüzden reel görünüm kapalı. Aşağıdaki her rakam nominal lira.',
};

/** Whether the deflated frame can be shown at all. */
export function basisAvailable(deflation: BistDeflation | null | undefined): boolean {
  return Boolean(deflation?.available);
}

/**
 * The frame actually drawn, which is not always the one asked for.
 *
 * The single most consequential function in this file. Returning `'real'` here
 * when nothing was deflated would paint nominal lira under a "Reel" label,
 * which is precisely the plausible-wrong-number failure this terminal refuses
 * to ship. The toggle is disabled in that state rather than merely defaulted
 * away from, so the reader is never silently moved between frames.
 */
export function effectiveBasis(
  requested: Basis,
  deflation: BistDeflation | null | undefined
): Basis {
  return basisAvailable(deflation) ? requested : 'nominal';
}

export function basisNotice(
  deflation: BistDeflation | null | undefined
): { tone: 'warn' | 'muted'; text: string } | null {
  if (!deflation) return null;
  if (!deflation.available) {
    const reason = deflation.reason;
    return {
      tone: 'warn',
      text: reason ? REASON_COPY[reason] : 'Reel görünüm şu anda hesaplanamıyor.',
    };
  }
  const provisional = deflation.provisional_periods ?? [];
  const uncovered = deflation.uncovered_periods ?? [];
  const parts: string[] = [];
  if (provisional.length > 0) {
    parts.push(
      `${provisional.join(', ')} en son yayımlanan endeksle çevrildi; kendi ayının TÜFE'si henüz açıklanmadı.`
    );
  }
  if (uncovered.length > 0) {
    parts.push(`${uncovered.join(', ')} endeks serisinden eski, reel karşılığı hesaplanmadı.`);
  }
  return parts.length > 0 ? { tone: 'muted', text: parts.join(' ') } : null;
}

/** What the reader should be told about one missing line. */
export function fieldState(payload: BistFinancials, field: string): FieldState {
  if (!payload.layout_fields.includes(field)) return 'absent_layout';
  return payload.available_fields.includes(field) ? 'present' : 'absent_unreported';
}

/**
 * A chart's state, which is its weakest field's.
 *
 * A panel that needs revenue and EBITDA cannot be drawn from revenue alone, and
 * half a chart is worse than a stated absence. `absent_layout` wins over
 * `absent_unreported` because it is the more fundamental fact.
 */
export function chartState(payload: BistFinancials, fields: string[]): FieldState {
  const states = fields.map((field) => fieldState(payload, field));
  if (states.some((state) => state === 'absent_layout')) return 'absent_layout';
  if (states.some((state) => state === 'absent_unreported')) return 'absent_unreported';
  return 'present';
}

export function absentCopy(payload: BistFinancials, fields: string[]): string {
  const state = chartState(payload, fields);
  const missing = fields
    .filter((field) => fieldState(payload, field) !== 'present')
    .map((field) => FIELD_LABELS[field] ?? field);
  const names = missing.join(', ');
  const layout = LAYOUT_LABELS[payload.layout] ?? payload.layout;
  if (state === 'absent_layout') {
    return `${names} kalemi ${layout} şablonunda yok. Bu şirketin hesap planı bu satırı taşımıyor, şirket bildirmemiş değil.`;
  }
  if (state === 'absent_unreported') {
    return `${payload.ticker} bu dönemlerde ${names} kalemini bildirmemiş.`;
  }
  return '';
}

function valuesFor(quarter: BistQuarter, basis: Basis) {
  return basis === 'real' ? quarter.real : quarter.nominal;
}

/**
 * One field across the window, in the chosen frame.
 *
 * A quarter with no deflated form is **omitted**, not plotted at zero. Zero on
 * a revenue chart is a company that sold nothing, which is a claim, and the
 * absence of a bar is not.
 */
export function quarterSeries(
  payload: BistFinancials,
  basis: Basis,
  fields: string[]
): FinancialSeries[] {
  return fields.map((field) => ({
    field,
    label: FIELD_LABELS[field] ?? field,
    points: payload.quarters
      .map((quarter) => ({ period: quarter.period, values: valuesFor(quarter, basis) }))
      .filter((entry) => entry.values !== null)
      .map((entry) => ({
        period: entry.period,
        value: entry.values?.[field] ?? null,
      })),
  }));
}

/**
 * Margins, which have no frame.
 *
 * Numerator and denominator sit in the same period's lira, so inflation divides
 * out exactly. The panel says so, which is a small piece of education the board
 * gets for free and which stops a reader wondering why one panel ignored the
 * toggle.
 */
export function marginSeries(payload: BistFinancials): FinancialSeries[] {
  const keys: Array<[string, string]> = [
    ['gross_margin', 'Brüt marj'],
    ['operating_margin', 'Faaliyet marjı'],
    ['net_margin', 'Net marj'],
  ];
  return keys
    .map(([key, label]) => ({
      field: key,
      label,
      points: payload.ratios.map((row) => ({
        period: row.period,
        value: (row as unknown as Record<string, number | null>)[key] ?? null,
      })),
    }))
    .filter((series) => series.points.some((point) => point.value !== null));
}

export interface IndexedRow {
  period: string;
  nominal: number | null;
  real: number | null;
}

export interface IndexedComparison {
  rows: IndexedRow[];
  /** The quarter both series are pinned to 100 at. */
  basePeriod: string | null;
  /** True when the oldest quarter had no deflated form and the base moved. */
  rebased: boolean;
}

/**
 * The board's argument, as two indexed series.
 *
 * Both start at 100 in the oldest quarter that has a deflated form, so the gap
 * between the lines is the whole reading: lira up, purchasing power flat or
 * down. Basing on the oldest quarter *overall* would leave the real series
 * starting partway across the chart against a nominal one that starts at the
 * left edge, and the two would no longer be comparable at all.
 */
export function indexedComparison(payload: BistFinancials, field: string): IndexedComparison {
  const usable = payload.quarters.filter(
    (quarter) =>
      quarter.nominal?.[field] != null &&
      quarter.nominal[field] !== 0 &&
      quarter.real?.[field] != null &&
      quarter.real[field] !== 0
  );
  if (usable.length === 0) {
    return { rows: [], basePeriod: null, rebased: false };
  }
  const base = usable[0];
  const baseNominal = base.nominal[field] as number;
  const baseReal = base.real?.[field] as number;
  return {
    rows: usable.map((quarter) => ({
      period: quarter.period,
      nominal: ((quarter.nominal[field] as number) / baseNominal) * 100,
      real: ((quarter.real?.[field] as number) / baseReal) * 100,
    })),
    basePeriod: base.period,
    rebased: base.period !== payload.quarters[0]?.period,
  };
}

export interface SeasonalRow {
  year: number;
  /** Q1 through Q4, `null` where the year has no such quarter on the board. */
  cells: (number | null)[];
}

/**
 * One field as a year-by-quarter grid.
 *
 * Turkish industrials are strongly seasonal and a quarter-on-quarter line
 * invites the reader to call a seasonal trough a decline. A grid puts the same
 * quarter of each year in one column, which is the comparison that means
 * something.
 */
export function seasonalGrid(payload: BistFinancials, basis: Basis, field: string): SeasonalRow[] {
  const byYear = new Map<number, (number | null)[]>();
  for (const quarter of payload.quarters) {
    if (!byYear.has(quarter.year)) byYear.set(quarter.year, [null, null, null, null]);
    const values = valuesFor(quarter, basis);
    // A year that reported two quarters keeps four cells with two holes. A
    // shortened row would slide Q3 under the Q1 column.
    byYear.get(quarter.year)![quarter.quarter - 1] = values?.[field] ?? null;
  }
  return Array.from(byYear.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([year, cells]) => ({ year, cells }));
}

/**
 * The divisor every series in one chart shares.
 *
 * Per-series scaling would make a stacked bar lie: two segments drawn at the
 * same height meaning different magnitudes. Picked from the largest absolute
 * value across everything the chart will draw.
 */
export function unitFor(values: Array<number | null | undefined>): {
  divisor: number;
  label: string;
} {
  const largest = Math.max(
    0,
    ...values.filter((value): value is number => typeof value === 'number').map(Math.abs)
  );
  if (largest >= 1e9) return { divisor: 1e9, label: 'milyar TL' };
  if (largest >= 1e6) return { divisor: 1e6, label: 'milyon TL' };
  if (largest >= 1e3) return { divisor: 1e3, label: 'bin TL' };
  return { divisor: 1, label: 'TL' };
}

/** The headline row. Unmeasurable figures render as a dash, never as zero. */
export function metricTiles(payload: BistFinancials, basis: Basis): Tile[] {
  const latest = payload.ratios[payload.ratios.length - 1];
  const newest = payload.quarters[payload.quarters.length - 1];
  const values = newest ? valuesFor(newest, basis) : null;
  const frame = basis === 'real' ? 'reel' : 'nominal';
  const tiles: Tile[] = [];

  if (payload.available_fields.includes('revenue')) {
    tiles.push({
      label: 'Son çeyrek hasılat',
      value: values?.revenue != null ? formatCompactTry(values.revenue) : EMPTY,
      note: `${newest?.period ?? EMPTY} · ${frame}`,
      title: 'Yalnızca o çeyreğin hasılatı; yılbaşından beri toplam değil.',
    });
  }

  if (payload.available_fields.includes('ebitda')) {
    tiles.push({
      label: 'FAVÖK marjı',
      value: formatPercent(latest?.ebitda_margin, 1),
      note: 'son 4 çeyrek',
      title: 'Marj bir orandır; enflasyon payda ile payda sadeleşir, iki görünümde de aynıdır.',
    });
  }

  if (payload.layout_fields.includes('total_debt')) {
    tiles.push({
      label: 'Net borç / FAVÖK',
      value: latest?.net_debt_ebitda != null ? `${latest.net_debt_ebitda.toFixed(1)}x` : EMPTY,
      note: 'son 4 çeyrek FAVÖK',
      title:
        'FAVÖK sıfır veya negatifken ölçülemez sayılır — bu durumda oran değil, kâr sorunu vardır.',
    });
  }

  tiles.push({
    label: 'Özkaynak kârlılığı',
    value: formatPercent(latest?.roe_ttm, 1),
    note: 'ortalama özkaynağa göre',
    title:
      'Payda açılış ve kapanış özkaynağının ortalaması. Yalnızca kapanış kullanmak, yıl içinde sermaye artıran şirkette oranı şişirir.',
  });

  // The tile renames itself rather than showing a dash under a "Reel" label.
  // A card headed with a frame it could not compute reads as a figure that
  // failed to load, when the truth is that the frame is unavailable — and the
  // nominal number it does have is worth showing under its own name.
  const deflated = payload.deflation.available;
  tiles.push(
    deflated
      ? {
          label: 'Reel hasılat büyümesi',
          value: formatSignedPercent(payload.ttm.real_revenue_growth, 1),
          note:
            payload.ttm.nominal_revenue_growth != null
              ? `nominal ${formatSignedPercent(payload.ttm.nominal_revenue_growth, 1)}`
              : 'yıllık',
          tone: toneClass(payload.ttm.real_revenue_growth),
          title: 'Son 4 çeyrek, önceki 4 çeyreğe karşı, TÜFE arındırılmış.',
        }
      : {
          label: 'Nominal hasılat büyümesi',
          value: formatSignedPercent(payload.ttm.nominal_revenue_growth, 1),
          note: 'enflasyon arındırılmadan',
          tone: toneClass(payload.ttm.nominal_revenue_growth),
          title:
            'Enflasyon serisi olmadığı için reel karşılığı hesaplanamadı. Türkiye’de yıllık nominal bir büyüme rakamının çoğu enflasyondur.',
        }
  );

  tiles.push({
    label: 'Zarar eden çeyrek',
    value: payload.ttm.loss_quarters != null ? `${payload.ttm.loss_quarters} / 4` : EMPTY,
    note: 'son 4 çeyrek',
    tone: payload.ttm.loss_quarters ? 'text-down' : undefined,
    title: 'Ölçülemiyorsa tahtada dört tam çeyrek yok demektir; sıfır ile aynı şey değildir.',
  });

  return tiles;
}

/** The deterministic header above the note. */
export function financialsChips(payload: BistFinancials): Array<{ text: string; title: string }> {
  const chips: Array<{ text: string; title: string }> = [
    {
      text: payload.layout_label,
      title: 'İş Yatırım bu şirketin tablolarını bu hesap planı altında yayımlıyor.',
    },
  ];
  if (payload.latest_period) {
    chips.push({
      text: `Son dönem ${payload.latest_period}`,
      title: 'Tahtadaki en yeni çeyrek.',
    });
  }
  chips.push({
    text: payload.deflation.available ? 'Reel (TÜFE)' : 'Nominal',
    title: payload.deflation.available
      ? `Her çeyrek ${payload.deflation.base_period} lirasına çevrildi.`
      : 'Enflasyon düzeltmesi bu sayfada uygulanamadı.',
  });
  return chips;
}
