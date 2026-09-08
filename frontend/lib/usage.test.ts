import { describe, expect, it } from 'vitest';

import type { AiUsage, UsageTotals } from './api';
import {
  breakdownRows,
  emptyMessage,
  featureLabel,
  formatDuration,
  formatTokens,
  ownKeyShare,
  tokenCoverage,
} from './usage';

function totals(over: Partial<UsageTotals> = {}): UsageTotals {
  return {
    requests: 10,
    failed: 0,
    prompt_tokens: 800,
    completion_tokens: 200,
    total_tokens: 1000,
    requests_without_token_data: 0,
    ...over,
  };
}

function usage(over: Partial<AiUsage> = {}): AiUsage {
  return {
    window: '30d',
    available: true,
    totals: totals(),
    by_feature: {},
    by_provider: {},
    by_key_owner: {},
    recent: [],
    ...over,
  };
}

describe('formatTokens', () => {
  it('keeps exact digits below a million', () => {
    // A token count is compared against a provider's quota; a rounded one
    // cannot be.
    expect(formatTokens(1000)).toBe('1,000');
    expect(formatTokens(999_999)).toBe('999,999');
  });

  it('abbreviates past a million, where the digits stop being actionable', () => {
    expect(formatTokens(2_400_000)).toBe('2.4M');
  });

  it('survives nonsense rather than rendering NaN', () => {
    expect(formatTokens(Number.NaN)).toBe('0');
    expect(formatTokens(-5)).toBe('0');
  });
});

describe('formatDuration', () => {
  it('uses milliseconds under a second and seconds above', () => {
    expect(formatDuration(430)).toBe('430ms');
    expect(formatDuration(2500)).toBe('2.5s');
  });

  it('renders a missing duration as a dash, not as zero', () => {
    expect(formatDuration(null)).toBe('—');
  });
});

describe('tokenCoverage', () => {
  it('reports complete when every call carried token data', () => {
    expect(tokenCoverage(totals()).complete).toBe(true);
  });

  it('says the totals are a floor when some provider reported nothing', () => {
    // Recorded as null rather than zero, so the request count can be right
    // while the token total is short. Saying which beats understating silently.
    const coverage = tokenCoverage(totals({ requests_without_token_data: 3 }));
    expect(coverage.complete).toBe(false);
    expect(coverage.missing).toBe(3);
    expect(coverage.note).toContain('floor');
    expect(coverage.note).toContain('3 calls');
  });

  it('gets the singular right', () => {
    expect(tokenCoverage(totals({ requests_without_token_data: 1 })).note).toContain('1 call ');
  });
});

describe('breakdownRows', () => {
  it('orders by tokens, largest first', () => {
    const rows = breakdownRows(
      {
        notes: totals({ total_tokens: 100 }),
        chat: totals({ total_tokens: 900 }),
      },
      1000
    );
    expect(rows.map((r) => r.key)).toEqual(['chat', 'notes']);
    expect(rows[0].share).toBeCloseTo(0.9);
  });

  it('falls back to request order when nothing reported tokens', () => {
    const rows = breakdownRows(
      {
        a: totals({ total_tokens: 0, requests: 2 }),
        b: totals({ total_tokens: 0, requests: 7 }),
      },
      0
    );
    expect(rows.map((r) => r.key)).toEqual(['b', 'a']);
    expect(rows[0].share).toBe(0);
  });

  it('handles an empty group', () => {
    expect(breakdownRows({}, 0)).toEqual([]);
  });
});

describe('emptyMessage', () => {
  it('distinguishes an unreadable table from an empty one', () => {
    // Telling a reader "no usage" when the query failed would be a lie in the
    // direction that hides a problem.
    const failed = emptyMessage(usage({ available: false }));
    expect(failed).toContain('not a measurement');

    const empty = emptyMessage(usage({ totals: totals({ requests: 0 }) }));
    expect(empty).toContain('No AI calls');
  });

  it('says nothing when there is something to show', () => {
    expect(emptyMessage(usage())).toBeNull();
  });
});

describe('ownKeyShare', () => {
  it('is the share of calls the reader paid for', () => {
    const value = ownKeyShare(
      usage({
        totals: totals({ requests: 10 }),
        by_key_owner: { user: totals({ requests: 4 }), server: totals({ requests: 6 }) },
      })
    );
    expect(value).toBeCloseTo(0.4);
  });

  it('is zero rather than NaN with no calls', () => {
    expect(ownKeyShare(usage({ totals: totals({ requests: 0 }) }))).toBe(0);
  });
});

describe('featureLabel', () => {
  it('translates the API vocabulary into the terminal’s', () => {
    expect(featureLabel('reports')).toBe('Reports & bet analysis');
    expect(featureLabel('background')).toBe('Scheduled jobs');
  });

  it('passes through a label it has not been taught', () => {
    expect(featureLabel('something-new')).toBe('something-new');
  });
});
