import { describe, expect, it } from 'vitest';
import { badgeAppearance, formatAge, formatDetail } from './health-format';

const NOW = 1_700_000_000_000; // fixed clock; the formatters take `now` explicitly

describe('badgeAppearance', () => {
  it('animates only when everything is healthy', () => {
    expect(badgeAppearance('live')).toMatchObject({ label: 'LIVE', pulse: true });
    expect(badgeAppearance('degraded').pulse).toBe(false);
    expect(badgeAppearance('offline').pulse).toBe(false);
  });
});

describe('formatAge', () => {
  it('returns null when a source has never succeeded', () => {
    expect(formatAge(null, NOW)).toBeNull();
  });

  it('picks the shortest honest unit', () => {
    expect(formatAge(NOW / 1000 - 5, NOW)).toBe('5s ago');
    expect(formatAge(NOW / 1000 - 120, NOW)).toBe('2m ago');
    expect(formatAge(NOW / 1000 - 7200, NOW)).toBe('2h ago');
  });
});

describe('formatDetail', () => {
  it('shows latency while healthy', () => {
    expect(formatDetail('ok', NOW / 1000 - 4, 118, null, NOW)).toBe('4s ago · 118ms');
  });

  it('replaces latency with the reason when something is wrong', () => {
    expect(formatDetail('down', NOW / 1000 - 90, 118, 'rate limited (429)', NOW)).toBe(
      '2m ago · rate limited (429)'
    );
  });

  it('does not claim an age for a source that has never been called', () => {
    expect(formatDetail('idle', null, null, null, NOW)).toBe('no data yet');
  });

  it('says a quiet source was last used, not that it failed', () => {
    expect(formatDetail('stale', NOW / 1000 - 2400, 118, null, NOW)).toBe('used 40m ago');
  });
});
