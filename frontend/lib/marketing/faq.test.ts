import { describe, expect, it } from 'vitest';
import { FAQ_ENTRIES, FAQ_GROUPS } from './faq';

describe('FAQ_GROUPS', () => {
  it('has unique, anchor-shaped group ids', () => {
    const ids = FAQ_GROUPS.map((group) => group.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it('has unique, anchor-shaped entry ids — they are links people keep', () => {
    const ids = FAQ_ENTRIES.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it('does not reuse a group id as an entry id', () => {
    const groupIds = new Set(FAQ_GROUPS.map((group) => group.id));
    for (const entry of FAQ_ENTRIES) expect(groupIds.has(entry.id)).toBe(false);
  });

  it('answers every question it asks', () => {
    for (const entry of FAQ_ENTRIES) {
      expect(entry.question.endsWith('?'), `"${entry.id}" is not a question`).toBe(true);
      expect(entry.answer.length).toBeGreaterThan(0);
      for (const paragraph of entry.answer) expect(paragraph.trim().length).toBeGreaterThan(0);
    }
  });

  it('flattens to exactly the entries the tally counts', () => {
    const expected = FAQ_GROUPS.reduce((total, group) => total + group.entries.length, 0);
    expect(FAQ_ENTRIES).toHaveLength(expected);
  });

  it('has no empty group', () => {
    for (const group of FAQ_GROUPS) expect(group.entries.length).toBeGreaterThan(0);
  });
});
