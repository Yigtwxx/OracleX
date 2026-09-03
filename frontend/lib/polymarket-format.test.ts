/**
 * How prediction-market numbers are shown, and what is shown when there are none.
 *
 * The through-line is that a missing value must never render as a confident one.
 * A market priced at 0 is the crowd saying it will not happen; a market with no
 * price is one we failed to read. They look identical the moment the second is
 * defaulted to the first, and a reader has no way to tell them apart afterwards.
 *
 * The other thing pinned here is the unit. Movements stay in probability points
 * because percent change ranks noise above news: 0.02 to 0.04 is +100% and two
 * cents, 0.45 to 0.62 is +17 points and the reason the market exists.
 */
import { describe, it, expect } from 'vitest';

import {
  NO_READING,
  driftTone,
  formatMoney,
  formatPoints,
  formatProbability,
  outcomeColors,
  leadingOutcome,
  oddsFraction,
  timeToClose,
} from './polymarket-format';

const NOW = Date.parse('2026-08-21T12:00:00Z');

describe('formatProbability', () => {
  it('shows a fraction as the percentage people reason in', () => {
    expect(formatProbability(0.625)).toBe('63%');
  });

  it('keeps a certainty distinct from a missing reading', () => {
    // The whole point: 0 is a claim, and absence is not.
    expect(formatProbability(0)).toBe('0%');
    expect(formatProbability(null)).toBe(NO_READING);
    expect(formatProbability(undefined)).toBe(NO_READING);
  });

  it('refuses a value that is not a number', () => {
    expect(formatProbability(Number.NaN)).toBe(NO_READING);
  });
});

describe('formatPoints', () => {
  it('reports a movement in points rather than percent', () => {
    // 0.45 → 0.62 is the move that had a cause. As a percentage it is +38%,
    // which is smaller than a two-cent wobble on a long shot.
    expect(formatPoints(0.17)).toBe('+17 pts');
  });

  it('signs a fall', () => {
    expect(formatPoints(-0.09)).toBe('-9 pts');
  });

  it('keeps a decimal for a move under a point', () => {
    // Rounding these to "0 pts" would show a drifting market as a still one.
    expect(formatPoints(0.004)).toBe('+0.4 pts');
  });

  it('has no reading for an absent movement', () => {
    expect(formatPoints(null)).toBe(NO_READING);
  });
});

describe('driftTone', () => {
  it('treats exactly zero as no direction', () => {
    expect(driftTone(0)).toBe('muted');
  });

  it('does not colour a movement we could not measure', () => {
    expect(driftTone(null)).toBe('muted');
  });

  it('colours real movement', () => {
    expect(driftTone(0.01)).toBe('up');
    expect(driftTone(-0.01)).toBe('down');
  });
});

describe('oddsFraction', () => {
  it('clamps a price quoted outside the range', () => {
    // The upstream occasionally quotes a hair past 1; unclamped, the marker
    // leaves its own bar.
    expect(oddsFraction(1.02)).toBe(1);
    expect(oddsFraction(-0.01)).toBe(0);
  });

  it('has no position for an unpriced outcome', () => {
    expect(oddsFraction(null)).toBeNull();
  });
});

describe('leadingOutcome', () => {
  it('picks the outcome the market favours', () => {
    const outcomes = [
      { label: 'Yes', price: 0.38 },
      { label: 'No', price: 0.62 },
    ];

    expect(leadingOutcome(outcomes)?.label).toBe('No');
  });

  it('ignores outcomes with no price rather than ranking them at zero', () => {
    const outcomes = [
      { label: 'Yes', price: null },
      { label: 'No', price: 0.4 },
    ];

    expect(leadingOutcome(outcomes)?.label).toBe('No');
  });

  it('has no favourite when nothing is priced', () => {
    // Falling back to the first outcome would invent a leader out of ordering.
    expect(leadingOutcome([{ label: 'Yes' }, { label: 'No' }])).toBeNull();
  });
});

describe('timeToClose', () => {
  it('counts down in the coarsest useful unit', () => {
    expect(timeToClose('2026-08-24T12:00:00Z', NOW)).toBe('3d');
    expect(timeToClose('2026-08-21T17:00:00Z', NOW)).toBe('5h');
    expect(timeToClose('2026-08-21T12:30:00Z', NOW)).toBe('30m');
  });

  it('never counts backwards past a deadline', () => {
    // A market past its close is awaiting resolution. "-3d" beside it reads as
    // a countdown running the wrong way rather than as a state.
    expect(timeToClose('2026-08-20T12:00:00Z', NOW)).toBeNull();
  });

  it('has nothing to say about a market with no close date', () => {
    expect(timeToClose(null, NOW)).toBeNull();
    expect(timeToClose('not a date', NOW)).toBeNull();
  });
});

describe('formatMoney', () => {
  it('abbreviates a market-sized figure', () => {
    // chain-format's formatUsd is built for sub-cent gas fees and prints this
    // as "$1937854.11", which is eight digits of precision nobody reads.
    expect(formatMoney(1_937_854.11)).toBe('$1.94M');
    expect(formatMoney(32_286_051)).toBe('$32.3M');
    expect(formatMoney(4_200_000_000)).toBe('$4.20B');
  });

  it('never signs a total', () => {
    // formatFlowUsd would render "+$1.9M". A volume is a total, not a flow, and
    // a leading plus implies a direction it does not have.
    expect(formatMoney(1_900_000).startsWith('+')).toBe(false);
  });

  it('keeps a missing figure distinct from an empty market', () => {
    expect(formatMoney(null)).toBe(NO_READING);
    expect(formatMoney(0)).toBe('$0');
  });
});

describe('outcomeColors', () => {
  it("gives Yes and No the terminal's own direction colours", () => {
    // A green "Yes" is the same green as a rising price. Consistency with the
    // rest of the terminal is worth more here than a distinct hue would be.
    const colors = outcomeColors([{ label: 'Yes' }, { label: 'No' }]);

    expect(colors.Yes).toBe('var(--up)');
    expect(colors.No).toBe('var(--down)');
  });

  it('never colours a nominal outcome green or red', () => {
    // Colouring a football match up/down asserts a good side and a bad side.
    const colors = outcomeColors([{ label: 'Team Spirit' }, { label: 'TEAM VISION' }]);

    expect(Object.values(colors)).not.toContain('var(--up)');
    expect(Object.values(colors)).not.toContain('var(--down)');
  });

  it('keeps every outcome in one market distinguishable', () => {
    const labels = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon'];

    const colors = outcomeColors(labels.map((label) => ({ label })));

    expect(new Set(Object.values(colors)).size).toBe(labels.length);
  });

  it('gives a label the same colour wherever it appears', () => {
    // So a team is recognisable from card to card, not just within one.
    const a = outcomeColors([{ label: 'Team Falcons' }, { label: 'Legacy' }]);
    const b = outcomeColors([{ label: 'Team Falcons' }, { label: 'Something Else' }]);

    expect(a['Team Falcons']).toBe(b['Team Falcons']);
  });
});
