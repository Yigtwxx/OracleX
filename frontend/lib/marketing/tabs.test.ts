import { describe, expect, it } from 'vitest';
import { MARKETING_TABS } from './tabs';

describe('MARKETING_TABS', () => {
  it('has unique hrefs', () => {
    const hrefs = MARKETING_TABS.map((tab) => tab.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('is entirely internal — every tab is a route, not a link off the site', () => {
    for (const tab of MARKETING_TABS) expect(tab.href).toMatch(/^\//);
  });

  /**
   * The tab row lights the active tab on an exact match, because `/` is a prefix
   * of every route and a prefix test would light the first tab everywhere. That
   * only holds while the root appears once.
   */
  it('has exactly one root route', () => {
    expect(MARKETING_TABS.filter((tab) => tab.href === '/')).toHaveLength(1);
  });

  it('labels every tab', () => {
    for (const tab of MARKETING_TABS) expect(tab.label.trim().length).toBeGreaterThan(0);
  });
});
