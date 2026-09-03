import { describe, expect, it } from 'vitest';
import { mempoolQueue } from './chain-format';

describe('mempoolQueue', () => {
  it('reads both halves of the queue', () => {
    expect(mempoolQueue(42_000, 3)).toBe('42.0K queued · 3 blk deep');
  });

  it('keeps a zero contested backlog, which is a real and common reading', () => {
    // Everything waiting is below the fee floor. Silence here would read as
    // "we could not measure the backlog", which is the opposite claim.
    expect(mempoolQueue(42_000, 0)).toBe('42.0K queued · 0 blk deep');
  });

  it('reports whichever half arrived', () => {
    expect(mempoolQueue(42_000, null)).toBe('42.0K queued');
    expect(mempoolQueue(null, 2)).toBe('2 blk deep');
  });

  it('returns null for the seven chains that have no mempool to read', () => {
    expect(mempoolQueue(null, null)).toBeNull();
    expect(mempoolQueue(undefined, undefined)).toBeNull();
  });
});
