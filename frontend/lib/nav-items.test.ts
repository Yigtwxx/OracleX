import { describe, expect, it } from 'vitest';

import {
  ADMIN_ITEM,
  BIST_NAV_ITEMS,
  GLOBAL_NAV_ITEMS,
  REALMS,
  realmFor,
  resolveActiveKey,
  resolveRealm,
} from '@/lib/nav-items';

describe('resolveRealm', () => {
  it('sends every other path to the global realm', () => {
    for (const path of ['/home', '/overview', '/macro', '/admin', '/u/abc', '/', '/faq']) {
      expect(resolveRealm(path)).toBe('global');
    }
  });

  it('claims /bist and everything under it', () => {
    for (const path of ['/bist', '/bist/fonlar', '/bist/hisseler/THYAO']) {
      expect(resolveRealm(path)).toBe('bist');
    }
  });

  it('claims the BIST marketing page too', () => {
    // The header sits on both sides of the app and has to light the same realm
    // on either — a reader on /borsa is reading about BIST.
    expect(resolveRealm('/borsa')).toBe('bist');
  });

  it('does not claim a path that merely starts with the same letters', () => {
    // A plain `startsWith('/bist')` would hand `/bistro` to the BIST realm and
    // render a tab set for a route that has nothing to do with it.
    expect(resolveRealm('/bistro')).toBe('global');
    expect(resolveRealm('/bist-something')).toBe('global');
    expect(resolveRealm('/borsalar')).toBe('global');
  });
});

describe('resolveActiveKey', () => {
  it('lights the tab whose href the path sits under', () => {
    expect(resolveActiveKey('/macro', GLOBAL_NAV_ITEMS)).toBe('macro');
    expect(resolveActiveKey('/community/42', GLOBAL_NAV_ITEMS)).toBe('community');
  });

  it('prefers the longest matching href', () => {
    // `/bist` is a prefix of every other BIST route. First-match order would
    // leave "Genel Bakış" lit on every page in the realm.
    expect(resolveActiveKey('/bist', BIST_NAV_ITEMS)).toBe('bist-overview');
    expect(resolveActiveKey('/bist/hisseler', BIST_NAV_ITEMS)).toBe('bist-stocks');
    expect(resolveActiveKey('/bist/hisseler/THYAO', BIST_NAV_ITEMS)).toBe('bist-stocks');
    expect(resolveActiveKey('/bist/isi-haritasi', BIST_NAV_ITEMS)).toBe('bist-heatmap');
    expect(resolveActiveKey('/bist/fonlar/PHE', BIST_NAV_ITEMS)).toBe('bist-funds');
    // `/bist/viop` is a prefix of neither, but the two tabs are adjacent and
    // a longest-match regression would light the wrong one.
    expect(resolveActiveKey('/bist/viop', BIST_NAV_ITEMS)).toBe('bist-viop');
    expect(resolveActiveKey('/bist/viop-haritasi', BIST_NAV_ITEMS)).toBe('bist-viop-map');
  });

  it('lights Overview, which has no item of its own', () => {
    // The Overview tab is spliced into the bar by Navigation rather than living
    // in GLOBAL_NAV_ITEMS, so it needs the explicit fallback.
    expect(resolveActiveKey('/overview', GLOBAL_NAV_ITEMS)).toBe('overview');
    expect(resolveActiveKey('/overview?type=nasdaq'.split('?')[0], GLOBAL_NAV_ITEMS)).toBe(
      'overview'
    );
  });

  it('lights Admin rather than the first tab', () => {
    expect(resolveActiveKey('/admin', GLOBAL_NAV_ITEMS)).toBe(ADMIN_ITEM.key);
  });

  it('lights Admin in a realm whose admin route nests under its own tabs', () => {
    // `/bist/admin` sits under `/bist`, so the realm's own admin item has to be
    // the one matched — the global `/admin` would leave "Genel Bakış" lit.
    const bist = realmFor('bist');
    expect(resolveActiveKey('/bist/admin', BIST_NAV_ITEMS, bist.adminItem)).toBe('admin');
  });

  it('falls back to the realm own first tab, not to a global one', () => {
    // An unrouted path inside the BIST realm must not light "Home", which is
    // not even in this bar.
    expect(resolveActiveKey('/bist-unknown', BIST_NAV_ITEMS)).toBe('bist-overview');
    expect(resolveActiveKey('/nowhere', GLOBAL_NAV_ITEMS)).toBe('home');
  });
});

describe('realm wiring', () => {
  it('resolves every realm key it declares', () => {
    for (const realm of REALMS) {
      expect(realmFor(realm.key)).toBe(realm);
    }
  });

  it('gives every realm a terminal and a marketing route that resolve back to it', () => {
    // A realm whose menu entry navigates outside its own realm would switch the
    // bar and then immediately switch it back.
    for (const realm of REALMS) {
      expect(resolveRealm(realm.href)).toBe(realm.key);
      expect(resolveRealm(realm.marketingHref)).toBe(realm.key);
    }
  });

  it('keeps terminal and marketing routes distinct', () => {
    // Route groups do not appear in the URL, so a realm whose two sides shared
    // an address would be a duplicate route and Next would refuse to build.
    const routes = REALMS.flatMap((realm) => [realm.href, realm.marketingHref]);
    expect(new Set(routes).size).toBe(routes.length);
  });

  it('keeps every realm own admin route inside that realm', () => {
    // The whole point of a per-realm admin route: opening the panel must not
    // switch the bar out from under the reader.
    for (const realm of REALMS) {
      expect(resolveRealm(realm.adminItem.href)).toBe(realm.key);
    }
  });

  it('keeps tab keys unique across both sets', () => {
    // `data-nav` is the styling and gesture hook in globals.css; two tabs
    // sharing a key would silently share a hover animation.
    const keys = [...GLOBAL_NAV_ITEMS, ...BIST_NAV_ITEMS, ADMIN_ITEM].map((item) => item.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
