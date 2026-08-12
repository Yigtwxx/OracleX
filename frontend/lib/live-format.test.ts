import { describe, it, expect } from 'vitest';
import { dayGroup, formatDistance, formatElapsed, formatUtcTime } from './live-format';

// A fixed instant to measure everything against: 2026-08-12T15:30:00Z.
const NOW = Date.parse('2026-08-12T15:30:00Z');

describe('formatUtcTime', () => {
  it('reports the instant in UTC regardless of the runner timezone', () => {
    // The whole point of the second timestamp on a row: every source this tab
    // aggregates publishes in UTC, so this figure has to be checkable against
    // a headline without the reader doing arithmetic.
    expect(formatUtcTime('2026-08-12T15:30:00Z')).toBe('15:30Z');
    expect(formatUtcTime('2026-08-12T12:30:00-04:00')).toBe('16:30Z');
  });

  it('pads to a fixed width so a column of them stays aligned', () => {
    expect(formatUtcTime('2026-08-12T04:05:00Z')).toBe('04:05Z');
  });
});

describe('formatDistance', () => {
  it('counts forwards and backwards', () => {
    expect(formatDistance('2026-08-12T16:28:00Z', NOW)).toBe('in 58m');
    expect(formatDistance('2026-08-12T19:42:00Z', NOW)).toBe('in 4h 12m');
    expect(formatDistance('2026-08-12T14:30:00Z', NOW)).toBe('1h ago');
  });

  it('collapses the moment itself rather than flickering between ±0m', () => {
    expect(formatDistance('2026-08-12T15:30:20Z', NOW)).toBe('now');
    expect(formatDistance('2026-08-12T15:29:40Z', NOW)).toBe('now');
  });

  it('goes quiet past a day, where the date on the row is the better answer', () => {
    expect(formatDistance('2026-08-14T09:00:00Z', NOW)).toBeNull();
  });
});

describe('formatElapsed', () => {
  it('counts up from the start as minutes and seconds', () => {
    expect(formatElapsed('2026-08-12T15:17:56Z', NOW)).toBe('12:04');
  });

  it('never runs negative before an event that has not started', () => {
    // The hero shows this beside a LIVE badge; a "-3:00" under it would be a
    // contradiction rather than a countdown.
    expect(formatElapsed('2026-08-12T15:33:00Z', NOW)).toBe('0:00');
  });
});

describe('dayGroup', () => {
  it('groups by calendar day, not by elapsed hours', () => {
    // Both of these are under 24h away, but only one of them is still today —
    // which is the distinction the panel's headings are making.
    const localMidnightTonight = new Date(NOW);
    localMidnightTonight.setHours(23, 30, 0, 0);
    const tomorrowMorning = new Date(NOW);
    tomorrowMorning.setDate(tomorrowMorning.getDate() + 1);
    tomorrowMorning.setHours(9, 0, 0, 0);

    expect(dayGroup(localMidnightTonight.toISOString(), NOW)).toBe('today');
    expect(dayGroup(tomorrowMorning.toISOString(), NOW)).toBe('tomorrow');
  });

  it('keeps something already past under today rather than inventing a group', () => {
    expect(dayGroup('2026-08-12T09:00:00Z', NOW)).toBe('today');
  });

  it('sends anything further out to the dated sections', () => {
    const later = new Date(NOW);
    later.setDate(later.getDate() + 3);
    expect(dayGroup(later.toISOString(), NOW)).toBe('later');
  });
});
