/**
 * The marketing surface's top-level sections.
 *
 * Three, and the order is the order of commitment: what the thing is, how you
 * build against it, what you are still worried about. `/` stays first and stays
 * the default — every other tab is something you go looking for.
 */

export interface MarketingTab {
  readonly href: string;
  readonly label: string;
}

export const MARKETING_TABS: readonly MarketingTab[] = [
  { href: '/', label: 'Product' },
  { href: '/developers', label: 'Developers' },
  { href: '/faq', label: 'FAQ' },
];
