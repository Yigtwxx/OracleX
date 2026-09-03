import { describe, expect, it } from 'vitest';

import type {
  BistFundsMarketFacts,
  BistMacroFacts,
  BistMarketFacts,
  BistPositioningFacts,
} from '@/lib/bist-api';
import { EMPTY } from '@/lib/bist-format';
import {
  FUND_STANCE_LABEL,
  FUND_STANCE_TONE,
  MACRO_STANCE_LABEL,
  MACRO_STANCE_TONE,
  MARKET_STANCE_LABEL,
  MARKET_STANCE_TONE,
  POSITIONING_STANCE_LABEL,
  POSITIONING_STANCE_TONE,
  formatPoints,
  fundChips,
  hasMarketRead,
  macroChips,
  marketChips,
  positioningChips,
} from '@/lib/bist-market-note';

function marketFacts(overrides: Partial<BistMarketFacts> = {}): BistMarketFacts {
  return {
    stance: 'narrow_rally',
    as_of: '2026-08-28',
    stale: false,
    index: {
      code: 'XU100',
      name: 'BIST 100',
      value: 11000,
      change_pct: 1.2,
      ytd_pct: 24,
      year_nominal_pct: 58,
      year_real_pct: -3,
    },
    breadth: { advancers: 118, decliners: 174, unchanged: 20, total: 312, advancer_pct: 40 },
    sentiment: { score: 38, label: 'Korku', measured: 300, components: [] },
    leaders: [],
    laggards: [],
    concentration: {
      sector: 'Finans',
      sector_weight_pct: 31,
      sector_change_pct: 2,
      top_ticker: 'THYAO',
      top_turnover_pct: 12,
      top5_turnover_pct: 31,
      concentrated: true,
    },
    valuation: { median_pe: 8.4, median_pb: 1.35, measured: 100 },
    macro: {
      inflation_pct: 33,
      ppi_pct: 25,
      policy_rate_pct: 39,
      real_policy_rate_pct: 4.5,
      unemployment_pct: 8.4,
      gdp_pct: 3.2,
      usdtry: 41.25,
      as_of: '2026-08-01',
    },
    viop: null,
    not_measured: ['oynaklık endeksi'],
    ...overrides,
  };
}

function fundFacts(overrides: Partial<BistFundsMarketFacts> = {}): BistFundsMarketFacts {
  return {
    stance: 'losing_to_inflation',
    fund_type: 'YAT',
    fund_type_label: 'Yatırım Fonları',
    stale: false,
    total: 1180,
    tradable: 1100,
    measured: 1150,
    median_nominal_pct: 28,
    median_real_pct: -4,
    spread: { p10_real_pct: -22, p90_real_pct: 31, width_pct: 53, measured: 1150 },
    inflation: {
      beat_count: 380,
      measured: 1150,
      beat_pct: 35,
      inflation_pct: 33,
      nominal_gain_real_loss: 610,
      nominal_gain_real_loss_measured: 1150,
      example: { code: 'AFA', nominal_pct: 31, real_pct: -2 },
    },
    risk_free: { rate_pct: 41, source: 'money_market_median', beat_count: 300 },
    leaders: [],
    laggards: [],
    risk_cohorts: [],
    deflatable_windows: ['1y'],
    ...overrides,
  };
}

function positioningFacts(overrides: Partial<BistPositioningFacts> = {}): BistPositioningFacts {
  return {
    stance: 'chasing_strength',
    as_of: '2026-08-28',
    stale: false,
    board: {
      total: 512,
      scored: 96,
      scored_pct: 18,
      unscored_tight_float: 22,
      unscored_quiet: 380,
      median_free_float_pct: 32,
      median_relative_volume: 0.75,
      hot_pct: 8,
      min_free_float_pct: 5,
      min_relative_volume: 1,
    },
    crowd: {
      cohort: 20,
      median_crowding: 25,
      median_free_float_pct: 12,
      median_relative_volume: 3,
      median_range_pct: 80,
      board_median_range_pct: 55,
      range_gap_pct: 25,
      names: [],
    },
    range: {
      measured: 500,
      median_pct: 55,
      near_high_pct: 12,
      near_low_pct: 6,
      near_extreme_pct: 10,
      median_rsi: 55,
      near_high_median_rsi: 65,
      overbought_pct: 10,
      oversold_pct: 4,
    },
    sectors: [
      {
        sector: 'Kimya',
        count: 12,
        share_pct: 40,
        median_relative_volume: 2.5,
        median_range_pct: 80,
      },
    ],
    sector_concentrated: true,
    futures: {
      covered: 38,
      total_open_interest: 1_200_000,
      growth_pct: 3.5,
      quadrants: { long_build: 14, short_build: 8, short_cover: 9, long_liquidation: 7 },
      dominant: 'long_build',
      movers: [],
    },
    not_measured: ['fonların hangi hisseyi tuttuğu'],
    ...overrides,
  };
}

const textOf = (chips: { text: string }[]) => chips.map((chip) => chip.text).join(' | ');

describe('formatPoints', () => {
  it('treats the value as percentage points, not as a fraction', () => {
    // The bug this file exists to prevent: `formatPercent(1.2)` would render
    // %120,0 because it multiplies by a hundred.
    expect(formatPoints(1.2)).toBe('%1,2');
  });

  it('writes the sign before the percent sign, as Turkish does', () => {
    expect(formatPoints(1.2, { sign: true })).toBe('+%1,2');
    expect(formatPoints(-1.2, { sign: true })).toBe('%-1,2');
  });

  it('omits the plus when a sign was not asked for', () => {
    expect(formatPoints(31)).toBe('%31,0');
  });

  it('honours the decimal count', () => {
    expect(formatPoints(8.42, { decimals: 0 })).toBe('%8');
  });

  it('renders missing as missing rather than as zero', () => {
    expect(formatPoints(null)).toBe(EMPTY);
    expect(formatPoints(undefined)).toBe(EMPTY);
    expect(formatPoints(Number.NaN)).toBe(EMPTY);
  });
});

describe('stance maps', () => {
  it('labels every equity stance the API can return', () => {
    const stances: BistMarketFacts['stance'][] = [
      'narrow_rally',
      'broad_rally',
      'narrow_selloff',
      'broad_selloff',
      'mixed',
    ];
    for (const stance of stances) {
      expect(MARKET_STANCE_LABEL[stance]).toBeTruthy();
      expect(MARKET_STANCE_TONE[stance]).toBeTruthy();
    }
  });

  it('tones an equity stance by the direction of the index', () => {
    expect(MARKET_STANCE_TONE.narrow_rally).toBe('text-up');
    expect(MARKET_STANCE_TONE.broad_selloff).toBe('text-down');
    expect(MARKET_STANCE_TONE.mixed).toBe('text-fg-muted');
  });

  it('labels every fund stance the API can return', () => {
    const stances: BistFundsMarketFacts['stance'][] = [
      'beating_inflation',
      'losing_to_inflation',
      'split',
    ];
    for (const stance of stances) {
      expect(FUND_STANCE_LABEL[stance]).toBeTruthy();
      expect(FUND_STANCE_TONE[stance]).toBeTruthy();
    }
  });
});

describe('marketChips', () => {
  it('carries the readings the screener below cannot show', () => {
    const text = textOf(marketChips(marketFacts()));
    expect(text).toContain('118↑ / 174↓');
    expect(text).toContain('ilk 5');
    expect(text).toContain('reel faiz');
  });

  it('states the index move with an explicit sign', () => {
    expect(textOf(marketChips(marketFacts()))).toContain('XU100 +%1,2');
  });

  it('drops the sentiment chip rather than showing a placeholder score', () => {
    const chips = marketChips(marketFacts({ sentiment: null }));
    expect(textOf(chips)).not.toContain('duyarlılık');
    // The rest of the header still renders — an unmeasured gauge costs a chip,
    // not the panel.
    expect(chips.length).toBeGreaterThan(0);
  });

  it('drops the real-return chip when the year could not be deflated', () => {
    const facts = marketFacts();
    const chips = marketChips({
      ...facts,
      index: { ...facts.index, year_real_pct: null },
    });
    expect(textOf(chips)).not.toContain('1Y reel');
  });

  it('survives a missing macro print', () => {
    const chips = marketChips(marketFacts({ macro: null }));
    expect(textOf(chips)).not.toContain('reel faiz');
    expect(chips.length).toBeGreaterThan(0);
  });

  it('never renders an em dash inside a chip it chose to show', () => {
    // A chip whose figure is missing should be absent, not present and empty.
    const chips = marketChips(
      marketFacts({
        sentiment: null,
        macro: null,
        valuation: { median_pe: null, median_pb: null, measured: 0 },
      })
    );
    expect(textOf(chips)).not.toContain(EMPTY);
  });
});

describe('fundChips', () => {
  it('leads with the median fund rather than the top of the table', () => {
    expect(fundChips(fundFacts())[0].text).toContain('medyan 1Y reel');
  });

  it('falls back to the nominal median and says so when nothing could be deflated', () => {
    const text = textOf(fundChips(fundFacts({ median_real_pct: null })));
    expect(text).toContain('nominal');
  });

  it('counts the funds that gained in lira and lost purchasing power', () => {
    expect(textOf(fundChips(fundFacts()))).toContain('610 fon');
  });

  it('omits the lira-gain chip when no fund did that', () => {
    const facts = fundFacts();
    const chips = fundChips({
      ...facts,
      inflation: { ...facts.inflation, nominal_gain_real_loss: 0 },
    });
    expect(textOf(chips)).not.toContain('reelde kaybetti');
  });

  it('names the estimate behind the risk-free rate in the tooltip', () => {
    const chip = fundChips(fundFacts()).find((entry) => entry.text.includes('risksiz faiz'));
    expect(chip?.title).toContain('Para piyasası');
  });

  it('drops the risk-free chip when the rate could not be estimated', () => {
    const facts = fundFacts();
    const chips = fundChips({
      ...facts,
      risk_free: { rate_pct: null, source: null, beat_count: null },
    });
    expect(textOf(chips)).not.toContain('risksiz faiz');
  });

  it('never renders an em dash inside a chip it chose to show', () => {
    const chips = fundChips(
      fundFacts({
        median_real_pct: null,
        median_nominal_pct: null,
        spread: { p10_real_pct: null, p90_real_pct: null, width_pct: null, measured: 0 },
        risk_free: { rate_pct: null, source: null, beat_count: null },
      })
    );
    expect(textOf(chips)).not.toContain(EMPTY);
  });
});

describe('positioningChips', () => {
  it('leads with the crowd against the board rather than with the crowd alone', () => {
    // A cohort median on its own is a figure the reader cannot place. The whole
    // read is the gap between it and the board it came from.
    const first = positioningChips(positioningFacts())[0].text;
    expect(first).toContain('kalabalık');
    expect(first).toContain('borsa');
  });

  it('drops the range chip rather than comparing against a missing board median', () => {
    const facts = positioningFacts();
    const chips = positioningChips({
      ...facts,
      crowd: { ...facts.crowd, board_median_range_pct: null },
    });
    expect(textOf(chips)).not.toContain('borsa %55');
  });

  it('carries the float the crowding is happening in', () => {
    expect(textOf(positioningChips(positioningFacts()))).toContain('halka açıklık %12');
  });

  it("names the sector's share of the whole board's crowding", () => {
    const chip = positioningChips(positioningFacts()).find((entry) =>
      entry.text.startsWith('Kimya')
    );
    expect(chip?.text).toContain('%40');
    expect(chip?.title).toContain('toplam kalabalıklık');
  });

  it('drops the futures chip when VİOP could not be read', () => {
    const chips = positioningChips(positioningFacts({ futures: null }));
    expect(textOf(chips)).not.toContain('açık pozisyon');
  });

  it('never renders an em dash inside a chip it chose to show', () => {
    const facts = positioningFacts();
    const chips = positioningChips({
      ...facts,
      board: { ...facts.board, median_free_float_pct: null },
      crowd: { ...facts.crowd, median_range_pct: null, board_median_range_pct: null },
      range: { ...facts.range, near_high_pct: null },
      sectors: [],
      futures: null,
    });
    expect(textOf(chips)).not.toContain(EMPTY);
  });

  it('gives neither behaviour a direction colour', () => {
    // Chasing strength is not a rally and bottom fishing is not a decline.
    // Colouring either would state a view the header is not entitled to.
    expect(POSITIONING_STANCE_TONE.chasing_strength).not.toContain('up');
    expect(POSITIONING_STANCE_TONE.bottom_fishing).not.toContain('down');
  });

  it('labels every stance the backend can send', () => {
    const stances: BistPositioningFacts['stance'][] = [
      'chasing_strength',
      'bottom_fishing',
      'dispersed',
    ];
    for (const stance of stances) {
      expect(POSITIONING_STANCE_LABEL[stance]).toBeTruthy();
      expect(POSITIONING_STANCE_TONE[stance]).toBeTruthy();
    }
  });
});

describe('hasMarketRead', () => {
  it('refuses to draw a frame around a board that could not be read', () => {
    // Null facts mean "we cannot see what is happening", which must not render
    // as "nothing is happening".
    expect(hasMarketRead(null)).toBe(false);
    expect(hasMarketRead(undefined)).toBe(false);
  });

  it('draws once there is a read', () => {
    expect(hasMarketRead(marketFacts())).toBe(true);
    expect(hasMarketRead(fundFacts())).toBe(true);
    expect(hasMarketRead(positioningFacts())).toBe(true);
  });
});

// ── Macro ──────────────────────────────────────────────────────────────────

function macroFacts(overrides: Partial<BistMacroFacts> = {}): BistMacroFacts {
  return {
    stance: 'real_positive',
    as_of: '2026-09-02',
    stale: false,
    rates: {
      policy_pct: 37,
      inflation_pct: 31.8,
      ppi_pct: 27.8,
      real_policy_pct: 4,
      ppi_cpi_gap_pct: -4,
      unemployment_pct: 8.1,
      gdp_pct: 2.3,
    },
    fx: {
      usdtry: 48.3,
      eurtry: 56,
      change_1m_pct: 1.5,
      change_3m_pct: 5,
      change_12m_pct: 17.5,
      carry_12m_pct: 19.5,
      series_points: 260,
    },
    prices: { month: '2026-1', mom_pct: 4.8, three_month_annualized_pct: 29.5 },
    measures: {
      window_days: 7,
      total: 3,
      by_kind: { circuit_breaker: 2, short_selling: 1 },
      tickers: ['THYAO', 'SASA'],
      latest_day: '2026-09-01',
    },
    not_measured: ['CDS primi'],
    ...overrides,
  };
}

describe('MACRO_STANCE_LABEL', () => {
  it('states the sign of the real rate without calling it tight or loose', () => {
    expect(MACRO_STANCE_LABEL.real_positive).toBe('Reel faiz pozitif');
    expect(MACRO_STANCE_LABEL.real_negative).toBe('Reel faiz negatif');
    expect(MACRO_STANCE_TONE.real_positive).toBe('text-up');
    expect(MACRO_STANCE_TONE.real_negative).toBe('text-down');
    expect(MACRO_STANCE_TONE.real_near_zero).toBe('text-fg-muted');
  });
});

describe('macroChips', () => {
  it('leads with the real rate, signed and in points', () => {
    const [first] = macroChips(macroFacts());
    expect(first.text).toBe('reel faiz +%4,0');
  });

  it('crosses the rate with the currency rather than printing the level', () => {
    const chips = macroChips(macroFacts());
    expect(chips.some((chip) => chip.text === '₺ 12 ay +%17,5')).toBe(true);
    expect(chips.some((chip) => chip.text === 'faiz − kur +%19,5')).toBe(true);
    expect(chips.some((chip) => chip.text.includes('48'))).toBe(false);
  });

  it('keeps producer and consumer prices apart', () => {
    const chips = macroChips(macroFacts());
    expect(chips.some((chip) => chip.text === 'ÜFE − TÜFE %-4,0')).toBe(true);
  });

  it('treats a calm week as a count and an absent tape as nothing', () => {
    const calm = macroChips(
      macroFacts({
        measures: { window_days: 7, total: 0, by_kind: {}, tickers: [], latest_day: null },
      })
    );
    expect(calm.some((chip) => chip.text === '7 günde 0 tedbir')).toBe(true);

    const blind = macroChips(macroFacts({ measures: null }));
    expect(blind.some((chip) => chip.text.includes('tedbir'))).toBe(false);
  });

  it('drops the pace of prices when the index is absent', () => {
    const chips = macroChips(macroFacts({ prices: null }));
    expect(chips.some((chip) => chip.text.includes('3 ay'))).toBe(false);
    expect(chips.some((chip) => chip.text === EMPTY)).toBe(false);
  });
});
