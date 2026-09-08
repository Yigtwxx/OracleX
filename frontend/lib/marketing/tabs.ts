/**
 * The marketing surface's top-level sections.
 *
 * The order is the order of commitment: what the thing is, how you build
 * against it, whether it has been right, what you are still worried about. `/`
 * stays first and stays the default — every other tab is something you go
 * looking for.
 *
 * Track record sits ahead of the FAQ rather than inside it deliberately. It is
 * the page most likely to talk a reader out of trusting the product, which is
 * exactly why burying it would undo the reason it exists.
 */

export interface MarketingTab {
  readonly href: string;
  readonly label: string;
}

export const MARKETING_TABS: readonly MarketingTab[] = [
  { href: '/', label: 'Product' },
  { href: '/developers', label: 'Developers' },
  { href: '/track-record', label: 'Track record' },
  { href: '/faq', label: 'FAQ' },
];
