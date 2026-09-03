/**
 * The VİOP derivations.
 *
 * Three properties carry most of the weight here, and all three are silent
 * failures rather than loud ones:
 *
 * * **Ordering by date, never by label.** `31 Ağu 26` and `30 Eki 26` sort
 *   alphabetically with October first, which inverts a term structure into a
 *   backwardation that does not exist. Nothing throws; the curve just points
 *   the other way.
 * * **An unpublished open-interest column is not a zero.** The payload's own
 *   `summary` flattens the two together, so anything drawn from that would
 *   state that nobody holds a name whose column came back empty.
 * * **The quadrant rule matches the backend's.** The scatter and the paragraph
 *   above it must count the same contracts.
 */

import { describe, expect, it } from 'vitest';

import type { BistViopFacts, BistViopMapFacts, ViopContract } from './bist-api';
import {
  boardTotals,
  futuresOnly,
  CURVE_SHAPE_LABEL,
  OTHER_KEY,
  curveShape,
  expiryLabel,
  expiryStacks,
  frontShare,
  oiChangeRatio,
  quadrantCounts,
  quadrantPoints,
  termCurve,
  underlyingBars,
  viopChips,
  viopMapChips,
  viopQuadrantOf,
  VIOP_MAP_STANCE_LABEL,
  VIOP_MAP_STANCE_TONE,
  VIOP_STANCE_LABEL,
  VIOP_STANCE_TONE,
} from './bist-viop';

function contract(overrides: Partial<ViopContract> = {}): ViopContract {
  return {
    contract: 'THYAO (31 Ağu 26) Vadeli',
    underlying: 'THYAO',
    expiry: '31 Ağu 26',
    expiry_date: '2026-08-31',
    kind: 'future',
    physical: true,
    last: 310.5,
    change_pct: 0.012,
    high: 312,
    low: 305,
    open_interest: 10_000,
    open_interest_change: 500,
    settlement: 310,
    previous_settlement: 306,
    traded_at: '18:10',
    ...overrides,
  };
}

// ── Futures against options ────────────────────────────────────────────────

describe('futuresOnly', () => {
  const board = [
    contract({ underlying: 'ISCTR', settlement: 13.16, open_interest: 3_190_152 }),
    contract({ underlying: 'ISCTR', kind: 'put', settlement: 0.13, open_interest: 62_003 }),
    contract({ underlying: 'USDTRY', kind: 'call', settlement: 0.09 }),
  ];

  it('keeps the futures and drops the options beside them', () => {
    expect(futuresOnly(board)).toHaveLength(1);
  });

  it('is what stops a premium being read as a price', () => {
    // 0.13 against 13.16 on the same underlying and expiry is not a term
    // structure in 99% backwardation, it is two different instruments.
    const mixed = termCurve(
      [
        contract({ underlying: 'ISCTR', expiry_date: '2026-09-30', settlement: 13.16 }),
        contract({
          underlying: 'ISCTR',
          kind: 'put',
          expiry_date: '2026-10-30',
          settlement: 0.13,
        }),
      ],
      'ISCTR'
    );
    expect(curveShape(mixed)).toBe('backwardation');
    expect(curveShape(termCurve(futuresOnly(board), 'ISCTR'))).toBeNull();
  });

  it('is what stops two books being added into one total', () => {
    // The put's 62,003 and the call's own book against the future's 3,190,152.
    expect(boardTotals(board).openInterest).toBe(3_190_152 + 62_003 + 10_000);
    expect(boardTotals(futuresOnly(board)).openInterest).toBe(3_190_152);
  });
});

// ── Quadrants ──────────────────────────────────────────────────────────────

describe('viopQuadrantOf', () => {
  it.each([
    [500, 0.02, 'long_build'],
    [500, -0.02, 'short_build'],
    [-500, 0.02, 'short_cover'],
    [-500, -0.02, 'long_liquidation'],
  ])('reads open interest %s against a %s move', (oi, price, expected) => {
    expect(viopQuadrantOf(contract({ open_interest_change: oi, change_pct: price }))).toBe(
      expected
    );
  });

  it.each([
    [0, 0.02],
    [500, 0],
    [null, 0.02],
    [500, null],
  ])('has no read for a contract sitting on an axis (%s, %s)', (oi, price) => {
    // Not a weak version of one of the four reads — the absence of one. Open
    // interest that did not move says nothing about who opened what.
    expect(viopQuadrantOf(contract({ open_interest_change: oi, change_pct: price }))).toBeNull();
  });
});

describe('oiChangeRatio', () => {
  it('measures the change against yesterday, not against today', () => {
    // A book that doubled overnight reads as +50% on today's denominator.
    expect(oiChangeRatio(contract({ open_interest: 200, open_interest_change: 100 }))).toBe(1);
  });

  it('refuses a book that did not exist yesterday', () => {
    expect(oiChangeRatio(contract({ open_interest: 100, open_interest_change: 100 }))).toBeNull();
    expect(oiChangeRatio(contract({ open_interest: null }))).toBeNull();
  });
});

describe('quadrantPoints', () => {
  it('drops the contracts it cannot place rather than pinning them to zero', () => {
    const points = quadrantPoints([
      contract(),
      contract({ underlying: 'AAA', open_interest: null }),
      contract({ underlying: 'BBB', change_pct: 0 }),
    ]);

    expect(points.map((point) => point.underlying)).toEqual(['THYAO']);
  });

  it('counts every quadrant, including the empty ones', () => {
    const counts = quadrantCounts(quadrantPoints([contract()]));
    expect(counts).toEqual({
      long_build: 1,
      short_build: 0,
      short_cover: 0,
      long_liquidation: 0,
    });
  });
});

describe('boardTotals', () => {
  const board = [
    contract({ open_interest: 10_000, open_interest_change: 1_000 }),
    contract({ underlying: 'AAA', open_interest: 10_000, open_interest_change: null }),
    contract({ underlying: 'BBB', open_interest: null, open_interest_change: 500 }),
  ];

  it('measures growth against yesterday', () => {
    const totals = boardTotals(board);
    expect(totals.openInterest).toBe(20_000);
    expect(totals.change).toBe(1_500);
    expect(totals.changeRatio).toBeCloseTo(1_500 / 18_500);
  });

  it('counts the contracts that published nothing rather than folding them in', () => {
    // The payload's own summary flattens the two together, so a board where a
    // third of the rows came back empty reads as one where they are all quiet.
    const totals = boardTotals(board);
    expect(totals.measured).toBe(2);
    expect(totals.silent).toBe(1);
  });

  it('has no ratio for a board that did not exist yesterday', () => {
    expect(boardTotals([]).changeRatio).toBeNull();
  });
});

// ── Open interest by underlying ────────────────────────────────────────────

describe('underlyingBars', () => {
  const board = [
    contract({ underlying: 'USDTRY', open_interest: 60_000, open_interest_change: 6_000 }),
    contract({
      underlying: 'USDTRY',
      expiry_date: '2026-10-30',
      open_interest: 30_000,
      open_interest_change: 0,
    }),
    contract({ underlying: 'THYAO', open_interest: 10_000, open_interest_change: 500 }),
  ];

  it('sums every expiry onto its underlying', () => {
    // The near month alone understates the position by roughly half, which is
    // the question a reader is actually asking.
    const [first] = underlyingBars(board);
    expect(first.underlying).toBe('USDTRY');
    expect(first.openInterest).toBe(90_000);
    expect(first.expiries).toBe(2);
  });

  it('ranks by book size and can be capped', () => {
    expect(underlyingBars(board, 1).map((bar) => bar.underlying)).toEqual(['USDTRY']);
  });

  it('keeps an unpublished column null rather than calling it an empty book', () => {
    const bars = underlyingBars([contract({ underlying: 'AAA', open_interest: null })]);
    expect(bars[0].openInterest).toBeNull();
    expect(bars[0].share).toBeNull();
  });

  it('shares are of everything actually measured', () => {
    const bars = underlyingBars(board);
    expect(bars[0].share).toBeCloseTo(90_000 / 100_000);
    expect(bars[1].share).toBeCloseTo(10_000 / 100_000);
  });

  it('reads a name that grew against its own yesterday', () => {
    const [usdtry] = underlyingBars(board);
    expect(usdtry.changeRatio).toBeCloseTo(6_000 / 84_000);
  });
});

// ── Term structure ─────────────────────────────────────────────────────────

describe('termCurve', () => {
  const strip = [
    contract({
      underlying: 'XU030',
      expiry: '30 Eki 26',
      expiry_date: '2026-10-30',
      settlement: 110,
    }),
    contract({
      underlying: 'XU030',
      expiry: '31 Ağu 26',
      expiry_date: '2026-08-31',
      settlement: 100,
    }),
    contract({ underlying: 'THYAO', settlement: 300 }),
  ];

  it('orders by date and never by the label', () => {
    // The whole reason the backend parses the expiry: sorted as strings, `30
    // Eki 26` comes before `31 Ağu 26` and the curve inverts.
    expect(termCurve(strip, 'XU030').map((point) => point.expiryDate)).toEqual([
      '2026-08-31',
      '2026-10-30',
    ]);
  });

  it('measures every point against the front month', () => {
    const points = termCurve(strip, 'XU030');
    expect(points[0].basis).toBe(0);
    expect(points[1].basis).toBeCloseTo(0.1);
  });

  it('drops contracts with no settlement or no date', () => {
    expect(
      termCurve([contract({ settlement: null }), contract({ expiry_date: null })], 'THYAO')
    ).toEqual([]);
  });
});

describe('curveShape', () => {
  it('needs two points before there is a term structure at all', () => {
    expect(curveShape(termCurve([contract()], 'THYAO'))).toBeNull();
  });

  it.each([
    [110, 'contango'],
    [90, 'backwardation'],
    [100.2, 'flat'],
  ])('reads a back month of %s against a front of 100 as %s', (settlement, expected) => {
    const points = termCurve(
      [
        contract({ underlying: 'X', expiry_date: '2026-08-31', settlement: 100 }),
        contract({ underlying: 'X', expiry_date: '2026-12-31', settlement }),
      ],
      'X'
    );
    expect(curveShape(points)).toBe(expected);
  });

  it('labels contango without calling it a signal', () => {
    // With rates this high a strip above spot is the cost of carry. The label
    // names the shape; the note beside it is what stops it reading as optimism.
    expect(CURVE_SHAPE_LABEL.contango).toBe('Contango');
  });
});

// ── The split across expiries ──────────────────────────────────────────────

describe('expiryLabel', () => {
  it('reads the month off the string rather than through Date', () => {
    // Through `Date`, a contract expiring at midnight moves into the previous
    // month for every viewer west of Istanbul.
    expect(expiryLabel('2026-10-30')).toBe('Eki 26');
    expect(expiryLabel('2026-01-30')).toBe('Oca 26');
  });

  it('hands back anything it cannot read', () => {
    expect(expiryLabel('nonsense')).toBe('nonsense');
  });
});

describe('expiryStacks', () => {
  const board = [
    contract({ underlying: 'USDTRY', expiry_date: '2026-08-31', open_interest: 60_000 }),
    contract({ underlying: 'THYAO', expiry_date: '2026-08-31', open_interest: 15_000 }),
    contract({ underlying: 'GARAN', expiry_date: '2026-08-31', open_interest: 5_000 }),
    contract({ underlying: 'USDTRY', expiry_date: '2026-10-30', open_interest: 20_000 }),
  ];

  it('gathers open interest per expiry, front month first', () => {
    const stacks = expiryStacks(board, ['USDTRY', 'THYAO']);
    expect(stacks.map((stack) => stack.label)).toEqual(['Ağu 26', 'Eki 26']);
    expect(stacks[0].total).toBe(80_000);
  });

  it('folds everything outside the named set into one band', () => {
    // Fifty slivers no legend could carry is not a chart.
    const stacks = expiryStacks(board, ['USDTRY', 'THYAO']);
    expect(stacks[0].byUnderlying[OTHER_KEY]).toBe(5_000);
  });

  it('excludes undated contracts rather than bucketing them', () => {
    // An "unknown" column sits at one end of a time axis and gets read as an
    // expiry, which is worse than being absent.
    const stacks = expiryStacks([...board, contract({ expiry_date: null })], ['USDTRY']);
    expect(stacks).toHaveLength(2);
  });

  it('measures how much of the book has not rolled', () => {
    expect(frontShare(expiryStacks(board, ['USDTRY']))).toBeCloseTo(0.8);
    expect(frontShare([])).toBeNull();
  });
});

// ── The note header ────────────────────────────────────────────────────────

function facts(overrides: Partial<BistViopFacts> = {}): BistViopFacts {
  return {
    stance: 'long_build',
    as_of: '2026-08-28',
    stale: false,
    board: {
      contracts: 148,
      underlyings: 42,
      measured: 130,
      silent: 18,
      undated: 0,
      total_open_interest: 1_842_000,
      open_interest_change: 36_000,
      growth_pct: 2,
      physical_pct: 25,
    },
    concentration: {
      top: [
        {
          underlying: 'USDTRY',
          open_interest: 1_100_000,
          share_pct: 60,
          oi_change_pct: 3,
          expiries: 6,
        },
      ],
      top_share_pct: 60,
      concentrated: true,
    },
    quadrants: {
      counts: { long_build: 40, short_build: 22, short_cover: 18, long_liquidation: 30 },
      weight_pct: { long_build: 55, short_build: 15, short_cover: 10, long_liquidation: 20 },
      on_axis: 38,
      measured: 110,
    },
    movers: [],
    curves: [],
    roll: { front: '2026-08-31', front_share_pct: 65, expiries: 7 },
    not_measured: ['opsiyon açık pozisyonu'],
    ...overrides,
  };
}

describe('viopChips', () => {
  it('leads with the book and how much of it moved', () => {
    const [first] = viopChips(facts());
    expect(first.text).toContain('AP');
    expect(first.text).toContain('+%2,0');
  });

  it('says how much of the day the stance actually rests on', () => {
    // A stance carrying a fifth of the movement and one carrying most of it are
    // the same word about very different sessions.
    const chips = viopChips(facts());
    expect(chips.some((chip) => chip.text.includes("hareketin %55,0'i"))).toBe(true);
  });

  it('names the silent contracts rather than letting totals imply completeness', () => {
    const chips = viopChips(facts());
    expect(chips.some((chip) => chip.text.includes('18/148'))).toBe(true);

    const complete = viopChips(facts({ board: { ...facts().board, silent: 0 } }));
    expect(complete.some((chip) => chip.text.includes('sözleşme AP yayımlamadı'))).toBe(false);
  });

  it('drops a reading it does not have rather than printing a placeholder', () => {
    const chips = viopChips(facts({ roll: { front: null, front_share_pct: null, expiries: 0 } }));
    expect(chips.some((chip) => chip.text.includes('yakın vade'))).toBe(false);
  });
});

describe('the stance header', () => {
  it('names the flow rather than the price', () => {
    // Both of these happen on a green day and they are opposite events.
    expect(VIOP_STANCE_LABEL.long_build).toBe('Yeni para uzun tarafta');
    expect(VIOP_STANCE_LABEL.short_cover).toBe('Kısalar kapatıyor');
  });

  it('tones by price direction, as everything else on this realm does', () => {
    expect(VIOP_STANCE_TONE.long_build).toBe('text-up');
    expect(VIOP_STANCE_TONE.short_cover).toBe('text-up');
    expect(VIOP_STANCE_TONE.short_build).toBe('text-down');
    expect(VIOP_STANCE_TONE.mixed).toBe('text-fg-muted');
  });
});

// ── Teminat haritası ────────────────────────────────────────────────────────

function mapFacts(overrides: Partial<BistViopMapFacts> = {}): BistViopMapFacts {
  return {
    stance: 'short_heavy',
    ticker: 'THYAO',
    as_of: '2026-08-31',
    stale: false,
    window: {
      requested: 120,
      covered: 120,
      undirected_sessions: 6,
      undirected_try: 34_000_000,
      basis_carried_sessions: 0,
      dropped_sessions: 0,
    },
    band: { psr_pct: 13.4, rungs_pct: [4.5, 8.9, 13.4], as_of: '20260901', run: '1' },
    book: {
      open_interest: 421_000,
      expiries: 3,
      standing_try: 26_443_000_000,
      long_try: 11_808_000_000,
      short_try: 14_635_000_000,
      long_share_pct: 45,
    },
    spot: { close: 302.25 },
    levels: {
      long: [
        { price: 285.64, distance_pct: -5.5, notional_try: 1_477_500_000 },
        { price: 268.78, distance_pct: -11, notional_try: 1_159_000_000 },
      ],
      short: [{ price: 356.81, distance_pct: 18, notional_try: 1_906_000_000 }],
    },
    session: {
      day: '2026-08-31',
      opened_long_try: 0,
      opened_short_try: 1_226_000_000,
      undirected_try: 0,
      closed_try: 937_500_000,
      oi_change: 8500,
      front_settlement_change_pct: -1.5,
    },
    not_measured: ['sürdürme teminatı seviyesi'],
    ...overrides,
  };
}

describe('VIOP_MAP_STANCE_LABEL', () => {
  it('names the side the bands sit on rather than a price direction', () => {
    expect(VIOP_MAP_STANCE_LABEL.long_heavy).toBe('Kitap uzun tarafta ağır');
    expect(VIOP_MAP_STANCE_LABEL.empty).toBe('Ayakta pozisyon yok');
    expect(VIOP_MAP_STANCE_TONE.long_heavy).toBe('text-up');
    expect(VIOP_MAP_STANCE_TONE.short_heavy).toBe('text-down');
    expect(VIOP_MAP_STANCE_TONE.balanced).toBe('text-fg-muted');
  });
});

describe('viopMapChips', () => {
  it('leads with what stands and which side holds it', () => {
    const [first, second] = viopMapChips(mapFacts());
    expect(first.text).toContain('ayakta');
    expect(first.text).toContain('₺');
    expect(second.text).toBe('uzun payı %45,0');
  });

  it('quotes the nearest band on each side with its signed distance', () => {
    const chips = viopMapChips(mapFacts());
    expect(chips.some((chip) => chip.text === 'uzun bant 285,64 · %-5,5')).toBe(true);
    expect(chips.some((chip) => chip.text === 'kısa bant 356,81 · +%18,0')).toBe(true);
  });

  it('names the undirected sessions only when there are some', () => {
    expect(viopMapChips(mapFacts()).some((chip) => chip.text === '6 seans yönsüz')).toBe(true);
    const directed = viopMapChips(
      mapFacts({ window: { ...mapFacts().window, undirected_sessions: 0 } })
    );
    expect(directed.some((chip) => chip.text.includes('yönsüz'))).toBe(false);
  });

  it('draws nothing for an empty field rather than a zero', () => {
    const chips = viopMapChips(
      mapFacts({
        stance: 'empty',
        book: { ...mapFacts().book, standing_try: 0, long_share_pct: null },
        levels: { long: [], short: [] },
      })
    );
    expect(chips.some((chip) => chip.text.includes('ayakta'))).toBe(false);
    expect(chips.some((chip) => chip.text.includes('bant'))).toBe(false);
  });
});
