import { describe, expect, it } from 'vitest';

import {
  MAX_MESSAGE_LENGTH,
  daysUntilEligible,
  describeReason,
  formatDayLabel,
  formatUnread,
  groupByDay,
  isValidOtp,
  isValidPhone,
  normalisePhone,
  previewText,
} from '@/lib/social';

describe('reason copy', () => {
  it('has a row for every reason the server can emit', () => {
    // These strings come from services/social/eligibility.py. If one is renamed
    // on either side the checklist silently loses a row, so the list is pinned
    // here rather than inferred.
    const emitted = [
      'email_unverified',
      'phone_unverified',
      'account_too_new',
      'recipient_blocked_you',
      'you_blocked_recipient',
      'recipient_disabled_dms',
      'cannot_message_yourself',
    ];
    for (const reason of emitted) {
      expect(describeReason(reason).title).not.toBe('You cannot message this person yet');
    }
  });

  it('still says something for a reason it has never seen', () => {
    expect(describeReason('invented_by_a_future_server').title).toBeTruthy();
  });
});

describe('daysUntilEligible', () => {
  const now = new Date('2026-08-12T12:00:00Z');

  it('counts the days left on a young account', () => {
    expect(daysUntilEligible('2026-08-07T12:00:00Z', 90, now)).toBe(85);
  });

  it('is zero once the account is old enough', () => {
    expect(daysUntilEligible('2020-01-01T00:00:00Z', 90, now)).toBe(0);
  });

  it('is zero when the rule is switched off, whatever the date', () => {
    expect(daysUntilEligible('2026-08-12T11:00:00Z', 0, now)).toBe(0);
  });

  it('rounds up, so a partial day never reads as none left', () => {
    // 15 May to 12 Aug is 89 days, plus the 12 hours to noon — 89.5 days old
    // against a 90-day rule. Half a day remains, and it must read as 1, not 0.
    expect(daysUntilEligible('2026-05-15T00:00:00Z', 90, now)).toBe(1);
  });

  it('is zero for a missing or unparseable date rather than NaN', () => {
    expect(daysUntilEligible(null, 90, now)).toBe(0);
    expect(daysUntilEligible('not a date', 90, now)).toBe(0);
  });
});

describe('formatUnread', () => {
  it('renders nothing at zero', () => {
    expect(formatUnread(0)).toBe('');
    expect(formatUnread(-1)).toBe('');
  });

  it('caps at 99+', () => {
    expect(formatUnread(99)).toBe('99');
    expect(formatUnread(100)).toBe('99+');
  });
});

describe('previewText', () => {
  it('collapses newlines so a multi-line message stays on one row', () => {
    expect(previewText('first\n\nsecond')).toBe('first second');
  });

  it('truncates with an ellipsis', () => {
    expect(previewText('x'.repeat(80), 10)).toBe(`${'x'.repeat(9)}…`);
  });

  it('says so when there is nothing to preview', () => {
    expect(previewText(null)).toBe('No messages yet');
    expect(previewText('   ')).toBe('No messages yet');
  });
});

describe('groupByDay', () => {
  const at = (iso: string) => ({ created_at: iso });
  const stamp = (item: { created_at: string }) => item.created_at;

  it('keeps one group per calendar day, in order', () => {
    const groups = groupByDay(
      [at('2026-08-10T09:00:00'), at('2026-08-10T21:00:00'), at('2026-08-11T08:00:00')],
      stamp
    );
    expect(groups).toHaveLength(2);
    expect(groups[0].items).toHaveLength(2);
    expect(groups[1].items).toHaveLength(1);
  });

  it('does not merge two runs of the same day that are separated', () => {
    // Consecutive-run grouping, not bucketing: the backend returns messages in
    // order, and re-sorting them here would hide an ordering bug upstream.
    const groups = groupByDay(
      [at('2026-08-10T09:00:00'), at('2026-08-11T09:00:00'), at('2026-08-10T23:00:00')],
      stamp
    );
    expect(groups).toHaveLength(3);
  });

  it('survives an unparseable timestamp', () => {
    const groups = groupByDay([at('nonsense')], stamp);
    expect(groups[0].day).toBe('unknown');
  });

  it('returns nothing for an empty thread', () => {
    expect(groupByDay([], stamp)).toEqual([]);
  });
});

describe('formatDayLabel', () => {
  const now = new Date(2026, 7, 12, 12, 0, 0); // 12 Aug 2026, local

  it('names today and yesterday', () => {
    expect(formatDayLabel('2026-08-12', now)).toBe('Today');
    expect(formatDayLabel('2026-08-11', now)).toBe('Yesterday');
  });

  it('writes an older date out', () => {
    expect(formatDayLabel('2026-08-01', now)).toMatch(/1/);
  });

  it('reads a bare date as local, not UTC', () => {
    // `new Date('2026-08-01')` is UTC midnight, which renders as 31 July
    // anywhere west of Greenwich. The label must not drift by a day.
    expect(formatDayLabel('2026-08-01', now)).not.toMatch(/31/);
  });

  it('renders nothing for an unknown day', () => {
    expect(formatDayLabel('unknown', now)).toBe('');
  });
});

describe('phone helpers', () => {
  it('accepts a well-formed E.164 number', () => {
    expect(isValidPhone('+905551112233')).toBe(true);
    expect(isValidPhone('  +14155552671 ')).toBe(true);
  });

  it('rejects numbers that cannot be dialled as given', () => {
    expect(isValidPhone('05551112233')).toBe(false); // no country code
    expect(isValidPhone('+0555111')).toBe(false); // leading zero after +
    expect(isValidPhone('+1234')).toBe(false); // too short
    expect(isValidPhone('+1234567890123456')).toBe(false); // too long
    expect(isValidPhone('not a phone')).toBe(false);
  });

  it('strips formatting characters', () => {
    expect(normalisePhone('+90 (555) 111-22-33')).toBe('+905551112233');
  });

  it('rewrites a leading 00 to +', () => {
    expect(normalisePhone('0090 555 111 22 33')).toBe('+905551112233');
  });

  it('leaves a bare national number alone rather than guessing a country', () => {
    expect(normalisePhone('05551112233')).toBe('05551112233');
  });
});

describe('isValidOtp', () => {
  it('wants exactly six digits', () => {
    expect(isValidOtp('123456')).toBe(true);
    expect(isValidOtp('12345')).toBe(false);
    expect(isValidOtp('1234567')).toBe(false);
    expect(isValidOtp('12345a')).toBe(false);
  });
});

describe('MAX_MESSAGE_LENGTH', () => {
  it('matches the backend cap', () => {
    // services/social/messages.py MAX_BODY and the CHECK constraint in 013.
    expect(MAX_MESSAGE_LENGTH).toBe(2000);
  });
});
