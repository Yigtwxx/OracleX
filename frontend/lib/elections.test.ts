/**
 * The elections board's derivations.
 *
 * Two invariants carry most of these. The first is that everything is measured
 * from UTC midnight: an election is an all-day event in its own country's time,
 * and a countdown computed against a local clock would put the same vote a day
 * nearer for a reader in Auckland than for one in Los Angeles.
 *
 * The second is that a missing reading and a zero reading are different claims.
 * A market that did not move in a week is a reading; a market with no history
 * is not, and the two must not share a rendering.
 */

import { describe, expect, it } from 'vitest';
import {
  Election,
  ElectionOdds,
  applyTierFilter,
  daysUntil,
  formatCountdown,
  formatMomentum,
  formatPrice,
  formatWhen,
  groupByMonth,
  horizonNote,
  leadOutcome,
  oddsSpread,
  oddsState,
  urgencyTier,
} from './elections';

// A fixed instant to measure everything against: 2026-08-24T12:00:00Z.
const NOW = Date.parse('2026-08-24T12:00:00Z');

function election(overrides: Partial<Election> = {}): Election {
  return {
    id: '2026-09-13-sweden',
    date: '2026-09-13',
    through: null,
    precision: 'day',
    country: 'Sweden',
    iso2: 'SE',
    flag: '🇸🇪',
    office: 'Parliament',
    minor: false,
    tier: 'watch',
    tickers: ['SEK=X'],
    note: null,
    odds: null,
    market_link: null,
    source_url: 'https://en.wikipedia.org/wiki/2026_national_electoral_calendar',
    ...overrides,
  };
}

function odds(overrides: Partial<ElectionOdds> = {}): ElectionOdds {
  return {
    event_slug: 'an-event',
    event_title: 'An event',
    url: 'https://polymarket.com/event/an-event',
    confidence: 'high',
    matched_on: ['tag', 'end_date'],
    volume_24h: 50_000,
    liquidity: 90_000,
    exclusive: true,
    outcomes: [{ label: 'Someone', price: 0.62, change_1w: 0.04 }],
    others: 0,
    ...overrides,
  };
}

describe('daysUntil', () => {
  it('counts whole days from UTC midnight so the figure does not drift with the clock', () => {
    // NOW is midday. A count from "right now" would make this 19.5 and round
    // differently depending on the hour the page was opened.
    expect(daysUntil('2026-09-13', NOW)).toBe(20);
    expect(daysUntil('2026-09-13', Date.parse('2026-08-24T23:59:00Z'))).toBe(20);
    expect(daysUntil('2026-09-13', Date.parse('2026-08-24T00:01:00Z'))).toBe(20);
  });

  it('treats today as zero and yesterday as negative', () => {
    expect(daysUntil('2026-08-24', NOW)).toBe(0);
    expect(daysUntil('2026-08-23', NOW)).toBe(-1);
  });

  it('crosses a year boundary without special-casing it', () => {
    expect(daysUntil('2027-01-16', Date.parse('2026-12-31T00:00:00Z'))).toBe(16);
  });

  it('reports nothing rather than NaN for an unparseable date', () => {
    expect(daysUntil('not a date', NOW)).toBeUndefined();
  });
});

describe('formatCountdown', () => {
  it('reads today and tomorrow the way a person would', () => {
    expect(formatCountdown(0)).toBe('Today');
    expect(formatCountdown(1)).toBe('Tomorrow');
  });

  it('switches from days to weeks to months as the horizon lengthens', () => {
    expect(formatCountdown(20)).toBe('20d');
    expect(formatCountdown(28)).toBe('4w');
    expect(formatCountdown(240)).toBe('8mo');
  });

  it('never shows a negative countdown', () => {
    // The board filters past elections server-side, but a row that slipped
    // through must not read "-3d" as though it were scheduled.
    expect(formatCountdown(-3)).toBe('Today');
  });

  it('declines to count down to a day nobody announced', () => {
    expect(formatCountdown(undefined)).toBe('–');
  });
});

describe('urgencyTier', () => {
  it('treats the next fortnight as imminent', () => {
    expect(urgencyTier(0)).toBe('imminent');
    expect(urgencyTier(14)).toBe('imminent');
  });

  it('puts a boundary day in the tighter tier', () => {
    expect(urgencyTier(15)).toBe('near');
    expect(urgencyTier(60)).toBe('near');
    expect(urgencyTier(61)).toBe('scheduled');
  });

  it('gives a month-precision row no urgency at all', () => {
    expect(urgencyTier(undefined)).toBe('scheduled');
  });
});

describe('formatWhen', () => {
  it('names the day for a dated row', () => {
    expect(formatWhen(election())).toBe('Sep 13');
  });

  it('names only the month when the article named only a month', () => {
    expect(formatWhen(election({ date: '2027-03-01', precision: 'month' }))).toBe('Mar');
  });

  it('spans a multi-day vote', () => {
    expect(formatWhen(election({ date: '2026-09-13', through: '2026-09-14' }))).toBe('Sep 13–14');
  });
});

describe('groupByMonth', () => {
  it('keeps calendar order across a year boundary', () => {
    const rows = [
      election({ date: '2026-12-06' }),
      election({ date: '2026-12-22' }),
      election({ date: '2027-01-16' }),
    ];

    expect(groupByMonth(rows).map((group) => group.label)).toEqual([
      'December 2026',
      'January 2027',
    ]);
  });

  it('labels a month without depending on the runner locale', () => {
    expect(groupByMonth([election()])[0].label).toBe('September 2026');
  });

  it('returns nothing for an empty board', () => {
    expect(groupByMonth([])).toEqual([]);
  });
});

describe('applyTierFilter', () => {
  it('keeps only countries the registry has a market view on', () => {
    const rows = [election(), election({ country: 'Tokelau', tier: null })];

    expect(applyTierFilter(rows, 'tracked').map((row) => row.country)).toEqual(['Sweden']);
  });

  it('hides a dependent territory even when its country is tracked', () => {
    const rows = [election({ country: 'Jersey', tier: 'watch', minor: true })];

    expect(applyTierFilter(rows, 'tracked')).toEqual([]);
  });

  it('leaves the board untouched when nothing is being filtered', () => {
    const rows = [election(), election({ tier: null })];

    expect(applyTierFilter(rows, 'all')).toHaveLength(2);
  });
});

describe('oddsState', () => {
  it('reports a price only when the backend stood behind one', () => {
    expect(oddsState(election({ odds: odds() }))).toBe('priced');
  });

  it('does not report a link-only match as priced', () => {
    // The distinction the whole join exists to make: a market we can point at
    // is not a market we can quote.
    const linked = election({
      market_link: {
        event_slug: 'a',
        event_title: 'A',
        url: 'https://polymarket.com/event/a',
        confidence: 'medium',
        matched_on: ['title'],
      },
    });

    expect(oddsState(linked)).toBe('linked');
  });

  it('does not report an unmatched election as a link', () => {
    expect(oddsState(election())).toBe('unmatched');
  });
});

describe('leadOutcome', () => {
  it('returns nothing rather than a zero when there are no outcomes', () => {
    expect(leadOutcome(odds({ outcomes: [] }))).toBeUndefined();
    expect(leadOutcome(null)).toBeUndefined();
  });

  it('takes the first outcome, which the backend already ordered by price', () => {
    const board = odds({
      outcomes: [
        { label: 'Ahead', price: 0.62, change_1w: null },
        { label: 'Behind', price: 0.3, change_1w: null },
      ],
    });

    expect(leadOutcome(board)?.label).toBe('Ahead');
  });
});

describe('oddsSpread', () => {
  it('measures the gap between the top two', () => {
    const board = odds({
      outcomes: [
        { label: 'Ahead', price: 0.62, change_1w: null },
        { label: 'Behind', price: 0.3, change_1w: null },
      ],
    });

    expect(oddsSpread(board)).toBeCloseTo(0.32);
  });

  it('reports nothing for a single-outcome market rather than a dead heat', () => {
    // An unopposed market and a tie are opposite readings; 0 would say "tie".
    expect(oddsSpread(odds())).toBeUndefined();
  });
});

describe('formatPrice', () => {
  it('rounds to whole percentage points', () => {
    expect(formatPrice(0.62)).toBe('62%');
  });

  it('refuses to round a near-certainty into a certainty', () => {
    expect(formatPrice(0.997)).toBe('>99%');
    expect(formatPrice(0.003)).toBe('<1%');
  });

  it('leaves a real 100% and a real 0% alone', () => {
    expect(formatPrice(1)).toBe('100%');
    expect(formatPrice(0)).toBe('0%');
  });
});

describe('formatMomentum', () => {
  it('reports a week move in percentage points with its direction', () => {
    expect(formatMomentum(0.04)).toBe('+4');
    expect(formatMomentum(-0.02)).toBe('−2');
  });

  it('keeps a flat week distinct from a missing reading', () => {
    expect(formatMomentum(0)).toBe('0');
    expect(formatMomentum(null)).toBeUndefined();
  });
});

describe('horizonNote', () => {
  it('says how far the board actually reaches', () => {
    const note = horizonNote([election(), election({ date: '2027-04-18' })], 40, true);

    expect(note).toContain('Through April 2027');
    expect(note).toContain('40');
  });

  it('names an odds outage instead of implying nothing is covered', () => {
    expect(horizonNote([election()], 40, false)).toContain('Odds unavailable');
  });

  it('still says something when the board is empty', () => {
    expect(horizonNote([], 40, true)).toContain('40');
  });
});
