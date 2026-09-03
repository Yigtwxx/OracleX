import { describe, expect, it } from 'vitest';
import { DEVELOPER_SECTIONS } from './sections';

describe('DEVELOPER_SECTIONS', () => {
  it('has unique, anchor-shaped ids', () => {
    const ids = DEVELOPER_SECTIONS.map((section) => section.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it('numbers the sections from 01, zero-padded so the rail column aligns', () => {
    DEVELOPER_SECTIONS.forEach((section, i) => {
      expect(section.index).toBe(String(i + 1).padStart(2, '0'));
    });
  });

  it('gives every section something to say', () => {
    for (const section of DEVELOPER_SECTIONS) {
      expect(section.body.length).toBeGreaterThan(0);
      expect(section.title.length).toBeGreaterThan(0);
      expect(section.label.length).toBeGreaterThan(0);
    }
  });

  /**
   * The rule the whole page rests on.
   *
   * Every figure on `/developers` is generated from the sources and checked in
   * CI. A number written into the prose escapes that entirely — it is a claim
   * that ages silently, and it ages on the one page arguing that this project
   * does not let numbers age. Spell it out in words, or let a figure carry it.
   */
  it('carries no digits in the prose — every number on the page is generated', () => {
    for (const section of DEVELOPER_SECTIONS) {
      const prose = section.body.join(' ');
      expect(prose, `section "${section.id}" states a number in prose`).not.toMatch(/[0-9]/);
    }
  });
});
