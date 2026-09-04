/**
 * The header's tab sets, and the realm each one belongs to.
 *
 * Lifted out of `Navigation.tsx` when the second realm arrived. One set inline
 * in the component was fine; two sets plus the realm resolver pushed that file
 * past the point where the rendering was still findable among the data, and the
 * resolver is the kind of thing that wants a test without mounting a header.
 */

/**
 * Every tab key in the app, as a closed union.
 *
 * The point is `NAV_ICONS` in `components/nav-icons.tsx`, which is typed
 * `Record<NavKey, ...>`: adding a tab here without giving it an icon is a
 * compile error rather than a tab that renders blank. `data-nav` in
 * globals.css keys off these same strings.
 */
export type NavKey =
  | 'home'
  | 'dashboard'
  | 'macro'
  | 'polymarket'
  | 'live'
  | 'chains'
  | 'ownership'
  | 'analysis'
  | 'chat'
  | 'derivatives'
  | 'community'
  | 'social'
  | 'profile'
  | 'admin'
  | 'bist-overview'
  | 'bist-stocks'
  | 'bist-financials'
  | 'bist-heatmap'
  | 'bist-funds'
  | 'bist-smart-money'
  | 'bist-ownership'
  | 'bist-kap'
  | 'bist-viop'
  | 'bist-viop-map'
  | 'bist-radar'
  | 'bist-macro'
  | 'bist-ipo';

export interface NavItem {
  key: NavKey;
  href: string;
  label: string;
  /** The tab's hue, as a `var(--nav-*)` reference rather than a Tailwind class.
      `.nav-tab` reads it out of `--nav-tint` for the icon, the label and the
      active underline; a class per state would have needed three verbatim
      literals per tab, since Tailwind cannot generate `hover:text-nav-${key}`. */
  tint: string;
  /** `derivatives` only: the label carries the board's own yellow→orange→red
      ramp, which no single token can express. See `.nav-heat-label` in
      globals.css. */
  labelClass?: string;
}

export const GLOBAL_NAV_ITEMS: NavItem[] = [
  // '/home', not '/': the root is the marketing landing page, which lives
  // outside this shell entirely.
  { key: 'home', href: '/home', label: 'Home', tint: 'var(--nav-home)' },
  {
    key: 'dashboard',
    href: '/dashboard',
    label: 'Dashboard',
    tint: 'var(--nav-dashboard)',
  },
  // Index 2 is not cosmetic: the bar renders slice(0, 2), then the Overview
  // dropdown, then slice(2) — so this is what puts Macro directly beside the
  // other market views rather than out past Chat.
  { key: 'macro', href: '/macro', label: 'Macro', tint: 'var(--nav-macro)' },
  // Beside Macro rather than out past Chat: the two answer the same question a
  // beat apart — Macro is what the world looks like, Live is what is happening
  // to it right now.
  // Between Macro and Live, which is where the question it answers belongs:
  // Macro is what the world looks like, this is what people are betting it does
  // next, and Live is what is happening to it right now. Putting it after Live
  // would have separated the two forward-looking tabs with the one about the
  // present.
  {
    key: 'polymarket',
    href: '/polymarket',
    label: 'Polymarket',
    tint: 'var(--nav-polymarket)',
  },
  { key: 'live', href: '/live', label: 'Live', tint: 'var(--nav-live)' },
  // Directly after Live, which continues the run rather than starting a new one:
  // Macro is what the world looks like, Live is what is happening to it, and
  // this is the state of the rails underneath while it does. Placing it here
  // also keeps the market views contiguous — Overview through Chains — instead
  // of leaving Ownership between them.
  { key: 'chains', href: '/chains', label: 'Chains', tint: 'var(--nav-chains)' },
  {
    key: 'ownership',
    href: '/ownership',
    label: 'Ownership',
    tint: 'var(--nav-ownership)',
  },
  {
    key: 'analysis',
    href: '/analysis',
    label: 'Analysis',
    tint: 'var(--nav-analysis)',
  },
  {
    key: 'chat',
    href: '/chat',
    label: 'Chat',
    tint: 'var(--nav-chat)',
  },
  {
    key: 'derivatives',
    href: '/derivatives',
    label: 'Derivatives',
    tint: 'var(--nav-heatmap-2)',
    // The heat ramp stays: the page still holds the three heatmap grids, and
    // the gradient is the only label on the bar that names a colour scale a
    // user will actually see inside it.
    labelClass: 'nav-heat-label',
  },
  {
    key: 'community',
    href: '/community',
    label: 'Community',
    tint: 'var(--nav-community)',
  },
  // Between Community and Profile because that is the order of the question it
  // answers: the board is everyone, this is the people on it, Profile is you.
  {
    key: 'social',
    href: '/social',
    label: 'Social',
    tint: 'var(--nav-social)',
  },
  { key: 'profile', href: '/profile', label: 'Profile', tint: 'var(--nav-profile)' },
];

/**
 * The BIST realm's tabs.
 *
 * Labels are Turkish and the rest of the codebase is not, which is deliberate:
 * "Takas Oranı" and "Bedelsiz" have no English form anybody trading Borsa
 * İstanbul would recognise, and half-translating the set would read worse than
 * either language alone. Identifiers, routes and comments stay English.
 *
 * Hues are reused freely from the global wheel because the two sets are never
 * in the bar at the same time — only separation *within* this set matters, and
 * these eight are spaced roughly 45° apart. Every one clears 4.5:1 on
 * --surface, same rule as the global set.
 */
export const BIST_NAV_ITEMS: NavItem[] = [
  {
    key: 'bist-overview',
    href: '/bist',
    label: 'Genel Bakış',
    tint: 'var(--nav-bist-overview)',
  },
  {
    key: 'bist-stocks',
    href: '/bist/hisseler',
    label: 'Hisseler',
    tint: 'var(--nav-bist-stocks)',
  },
  // Directly after Hisseler, because that is the order of the question: the
  // screener says which company, and this says what it earns. A reader arrives
  // here from a row in that table, not from the top of the bar.
  {
    key: 'bist-financials',
    href: '/bist/bilanco',
    label: 'Bilanço',
    tint: 'var(--nav-bist-financials)',
  },
  // Beside Hisseler rather than beside VİOP: the board is the equity screener
  // seen as area instead of as rows, and a reader who has just been through the
  // table is the one who reaches for it.
  {
    key: 'bist-heatmap',
    href: '/bist/isi-haritasi',
    label: 'Isı Haritası',
    tint: 'var(--nav-bist-heatmap)',
  },
  {
    key: 'bist-funds',
    href: '/bist/fonlar',
    label: 'Fonlar',
    tint: 'var(--nav-bist-funds)',
  },
  // "Konumlanma", not the "Akıllı Para" this tab was first called.
  //
  // The original promise was a fund-to-stock cross index — invert every TEFAS
  // portfolio and answer which funds moved into a name. TEFAS withdrew
  // portfolio breakdowns from its public API in the 2026 rewrite and KAP
  // publishes holdings only as prose attachments, so that board cannot be built
  // from anything public. What the tab does show — free float, unusual volume,
  // range position, futures open interest — is published positioning, which is
  // a narrower and honest claim. The label follows the content rather than the
  // other way round; the route keeps its path so existing links still work.
  {
    key: 'bist-smart-money',
    href: '/bist/akilli-para',
    label: 'Konumlanma',
    tint: 'var(--nav-bist-smart-money)',
  },
  // Beside Konumlanma, because it answers the question that tab was first
  // meant to: who actually holds these companies. Konumlanma reads the tape;
  // Ortaklık reads the shareholder table and the fund filings.
  {
    key: 'bist-ownership',
    href: '/bist/ortaklik',
    label: 'Ortaklık',
    tint: 'var(--nav-bist-ownership)',
  },
  {
    key: 'bist-kap',
    href: '/bist/kap',
    label: 'KAP',
    tint: 'var(--nav-bist-kap)',
  },
  {
    key: 'bist-viop',
    href: '/bist/viop',
    label: 'VİOP',
    tint: 'var(--nav-bist-viop)',
  },
  // "Teminat Bantları", not anything starting with VİOP: the tab beside it
  // already does, and two labels sharing a first word are two labels nobody
  // reads apart at a glance. Not "Haritası" either, although the route still
  // says so: the page stopped being a map when it started drawing Takasbank's
  // scan range instead of a margin-call level, and its own title says
  // "Tarama Bantları". The tab keeps the shorter half of that so it sits in
  // the bar at the width of its neighbours; the route keeps its path so
  // existing links still work.
  {
    key: 'bist-viop-map',
    href: '/bist/viop-haritasi',
    label: 'Teminat Bantları',
    tint: 'var(--nav-bist-viop-map)',
  },
  // Beside Makro rather than beside Hisseler: every tab before it describes
  // the market as it is; this one is the first that asks "so which of these,
  // now?" — and a reader arrives at that question last, not first.
  {
    key: 'bist-radar',
    href: '/bist/radar',
    label: 'Radar',
    tint: 'var(--nav-bist-radar)',
  },
  {
    key: 'bist-macro',
    href: '/bist/makro',
    label: 'Makro',
    tint: 'var(--nav-bist-macro)',
  },
  // Last in the set, which is where its question belongs: every tab before it
  // describes companies already trading, and this one is about the ones that
  // are not yet. It is also the realm's only board whose calendar comes from a
  // third-party site rather than from an exchange or a regulator.
  {
    key: 'bist-ipo',
    href: '/bist/halka-arz',
    label: 'Halka Arz',
    tint: 'var(--nav-bist-ipo)',
  },
];

// Kept out of the tab sets because it is conditional: only an admin ever sees
// it. The tab is cosmetic — the panel renders "does not exist" and every route
// behind it 403s — but there is no reason to show a door nobody else can open.
const adminItemAt = (href: string): NavItem => ({
  key: 'admin',
  href,
  label: 'Admin',
  tint: 'var(--nav-admin)',
});

/**
 * One admin route per realm, mounting the same panel.
 *
 * The realm is read off the path, so a single `/admin` shared by both sets was
 * a path under neither: opening the panel from a BIST board switched the header
 * to the global bar and stranded the reader on the other side of the app.
 * `/bist/admin` is the same component at an address that still says which realm
 * it was opened from, which keeps the rule that the URL is the only place a
 * realm is recorded.
 */
export const ADMIN_ITEM: NavItem = adminItemAt('/admin');
const BIST_ADMIN_ITEM: NavItem = adminItemAt('/bist/admin');

export type RealmKey = 'global' | 'bist';

/**
 * The handful of shared controls whose wording is not the same in both realms.
 *
 * Not an i18n layer, and deliberately not the start of one: these are the four
 * strings on chrome that sits above both products, and a translation framework
 * for four strings would be more machinery than the problem. A fifth realm, or
 * a fifth string that varies, is the signal to stop and do this properly.
 */
export interface RealmCopy {
  openTerminal: string;
  signIn: string;
  signUp: string;
  /** Accessible name for the logo menu trigger. */
  switcher: string;
}

export interface Realm {
  key: RealmKey;
  label: string;
  /** One line under the label in the switcher — what this realm actually is. */
  description: string;
  /** The realm's terminal entry point. */
  href: string;
  /** The realm's marketing page. Every realm has both, and the logo menu links
      to whichever side of the app the reader is currently on — jumping someone
      from a product page straight into a terminal is a different action than
      the one the menu appears to offer. */
  marketingHref: string;
  copy: RealmCopy;
  items: NavItem[];
  /** The realm's own admin route. Rendered only for an admin, and separate from
      `items` because it is conditional rather than part of the set. */
  adminItem: NavItem;
}

export const REALMS: Realm[] = [
  {
    key: 'global',
    label: 'Kripto / Nasdaq',
    description: 'Küresel piyasalar ve zincirler',
    // '/home' rather than the last visited tab: there is no history to restore
    // across a realm switch, and Home is the one tab that orients you.
    href: '/home',
    marketingHref: '/',
    copy: {
      openTerminal: 'Open terminal',
      signIn: 'Sign in',
      signUp: 'Sign up',
      switcher: 'Select market',
    },
    items: GLOBAL_NAV_ITEMS,
    adminItem: ADMIN_ITEM,
  },
  {
    key: 'bist',
    label: 'BIST 100',
    description: 'Borsa İstanbul, TEFAS, KAP',
    href: '/bist',
    // '/borsa' rather than '/bist': route groups do not appear in the URL, so a
    // marketing page at `(marketing)/bist` and the terminal at `(app)/bist`
    // would be the same route and Next refuses to build. The Turkish word is
    // the better marketing address anyway.
    marketingHref: '/borsa',
    copy: {
      openTerminal: 'BIST terminalini aç',
      signIn: 'Giriş yap',
      signUp: 'Kayıt ol',
      switcher: 'Piyasa seç',
    },
    items: BIST_NAV_ITEMS,
    adminItem: BIST_ADMIN_ITEM,
  },
];

/**
 * Which realm a path belongs to.
 *
 * Checks both sides of the app: `/bist` is the BIST terminal and `/borsa` is
 * its marketing page, and the header has to light the same realm on either.
 * Everything else — including `/`, `/developers` and `/faq` — is global.
 */
export function resolveRealm(pathname: string): RealmKey {
  const bist = realmFor('bist');
  return isUnder(pathname, bist.href) || isUnder(pathname, bist.marketingHref) ? 'bist' : 'global';
}

export function realmFor(key: RealmKey): Realm {
  // Non-null: `RealmKey` is the union of the keys in REALMS, so this cannot miss.
  return REALMS.find((realm) => realm.key === key)!;
}

/**
 * Segment-aware prefix test.
 *
 * `pathname.startsWith(href)` alone would light "Genel Bakış" (`/bist`) for
 * every page under it, and would also match a hypothetical `/bistro`. Both are
 * ruled out by requiring the match to end at a segment boundary.
 */
function isUnder(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The tab to light for a path, within one realm's set.
 *
 * Longest href wins. The global set has no nested routes today so any order
 * would do there, but `/bist/hisseler` sits under `/bist` — first-match would
 * hand every BIST page to the overview tab.
 *
 * `adminItem` is the realm's, not a constant: `/bist/admin` sits under `/bist`,
 * so matching the global `/admin` here would light "Genel Bakış" on the panel.
 */
export function resolveActiveKey(
  pathname: string,
  items: NavItem[],
  adminItem: NavItem = ADMIN_ITEM
): string {
  // Matched against the admin item too, or the panel would light the first tab.
  const match = [...items, adminItem]
    .filter((item) => isUnder(pathname, item.href))
    .sort((a, b) => b.href.length - a.href.length)[0];
  if (match) return match.key;
  if (isUnder(pathname, '/overview')) return 'overview';
  return items[0]?.key ?? 'home';
}
