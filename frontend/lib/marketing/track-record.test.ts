import { describe, expect, it } from 'vitest';
import { TRACK_RECORD_SECTIONS } from './track-record';

describe('TRACK_RECORD_SECTIONS', () => {
  it('has unique, anchor-shaped ids', () => {
    const ids = TRACK_RECORD_SECTIONS.map((section) => section.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it('numbers the sections from 01, zero-padded so the rail column aligns', () => {
    TRACK_RECORD_SECTIONS.forEach((section, i) => {
      expect(section.index).toBe(String(i + 1).padStart(2, '0'));
    });
  });

  it('gives every section something to say', () => {
    for (const section of TRACK_RECORD_SECTIONS) {
      expect(section.body.length).toBeGreaterThan(0);
      expect(section.title.length).toBeGreaterThan(0);
      expect(section.label.length).toBeGreaterThan(0);
    }
  });

  /**
   * The rule matters more here than on `/developers`. This is the page arguing
   * that the terminal's claims are checked rather than asserted; a hit rate
   * frozen into a sentence would be the one number on it that nothing verifies.
   */
  it('carries no digits in the prose — every number comes from the live record', () => {
    for (const section of TRACK_RECORD_SECTIONS) {
      const prose = section.body.join(' ');
      expect(prose, `section "${section.id}" states a number in prose`).not.toMatch(/[0-9]/);
    }
  });
});
