'use client';

import { useState, useRef, type CSSProperties } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import { BarChart3, ChevronDown, Bitcoin, LineChart } from 'lucide-react';
import AlarmBell from '@/components/alarms/AlarmBell';
import LiveStatusBadge from '@/components/LiveStatusBadge';
import NightShiftBadge from '@/components/bist/NightShiftBadge';
import PizzaIndexBadge from '@/components/PizzaIndexBadge';
import RealmSwitcher from '@/components/RealmSwitcher';
import { NAV_ICONS } from '@/components/nav-icons';
import { useIsAdmin } from '@/hooks/useAdmin';
import { useUnreadCount } from '@/hooks/useSocial';
import { realmFor, resolveActiveKey, resolveRealm, type NavItem } from '@/lib/nav-items';
import { formatUnread } from '@/lib/social';

const DROPDOWN_CLOSE_DELAY_MS = 200;

// No colour classes here: `.nav-tab` owns the rest / hover / active colours so
// that one `--nav-tint` per item drives all three (see globals.css).
// Height derived from the track rather than repeated as a literal, so the bar's
// height lives in exactly one place — the header. The extra pixel is what pairs
// with `-mb-px`: the tab reaches one pixel past the track, onto the header's own
// bottom border, and the negative margin keeps that pixel from growing the row.
// At a flat `h-full` the two cancel to a half-pixel offset and the active
// underline sits just shy of the header line instead of on it.
// No `transition-colors` here, and that is the point rather than an omission.
// The utility covers `border-color` along with `color`, so the outgoing tab's
// underline faded out while the incoming one faded in and both were on screen
// together for the length of the transition — long enough, across an App Router
// navigation, to read as the previous tab leaving a trace. `.nav-tab` in
// globals.css transitions the label colour by name instead: the underline is a
// position indicator, and an indicator has to move rather than cross-fade.
const NAV_TAB_CLASS = [
  'nav-tab flex items-center gap-2 h-[calc(100%_+_1px)] px-3 text-sm font-medium whitespace-nowrap shrink-0',
  'border-b-2 -mb-px',
].join(' ');

// Cast because `CSSProperties` has no index signature for custom properties —
// React passes `--nav-tint` straight through to the inline style regardless.
const tintStyle = (tint: string): CSSProperties => ({ '--nav-tint': tint }) as CSSProperties;

function NavTab({
  item,
  isActive,
  badge,
}: {
  item: NavItem;
  isActive: boolean;
  /** Unread count, rendered as a pill after the label. Empty string hides it. */
  badge?: string;
}) {
  const { key, href, label, tint, labelClass } = item;
  const Icon = NAV_ICONS[key];
  return (
    <Link
      href={href}
      // `data-active` rather than a conditional class: the underline and the two
      // lit states are all one CSS rule keyed off it, and it doubles as the hook
      // the heatmap gradient needs on the *label* while living on the link.
      data-active={isActive}
      // Which gesture the icon plays. On the link rather than the svg so the
      // gesture rules can key off the tab's own `:hover`.
      data-nav={key}
      className={NAV_TAB_CLASS}
      style={tintStyle(tint)}
    >
      <Icon className="w-3.5 h-3.5" />
      <span className={labelClass}>{label}</span>
      {badge && (
        <span className="rounded-full bg-accent px-1.5 text-2xs font-semibold text-white">
          {badge}
        </span>
      )}
    </Link>
  );
}

export default function Navigation() {
  const pathname = usePathname();
  const { data: adminSession } = useIsAdmin();
  // Polled every 20s and only while signed in; see hooks/useSocial.ts.
  const { data: unread } = useUnreadCount();
  const searchParams = useSearchParams();
  const [showDropdown, setShowDropdown] = useState(false);
  const [dropdownPos, setDropdownPos] = useState({ left: 0, top: 0 });
  const closeTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const triggerRef = useRef<HTMLDivElement>(null);

  // The realm decides the whole tab set. Derived from the path rather than held
  // in a store: a realm is a place in the app, so the URL already says which one
  // you are in, and a second copy of that could disagree with it.
  const realmKey = resolveRealm(pathname);
  const realm = realmFor(realmKey);
  const navItems = realm.items;
  const activeKey = resolveActiveKey(pathname, navItems, realm.adminItem);

  const overviewType = searchParams.get('type') === 'nasdaq' ? 'nasdaq' : 'crypto';
  const isOverview = activeKey === 'overview';

  const handleDropdownOpen = () => {
    clearTimeout(closeTimeoutRef.current);
    closeTimeoutRef.current = undefined;
    // The nav scrolls horizontally, and `overflow-x` forces `overflow-y` to
    // clip too — an absolutely positioned menu is cut off by the 56px bar.
    // Positioning it fixed, against the trigger, keeps it outside that clip.
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) {
      setDropdownPos({ left: rect.left, top: rect.bottom });
    }
    setShowDropdown(true);
  };

  const handleDropdownClose = () => {
    closeTimeoutRef.current = setTimeout(() => setShowDropdown(false), DROPDOWN_CLOSE_DELAY_MS);
  };

  const subItemClass = (isSelected: boolean): string =>
    [
      'w-full flex items-center gap-2.5 px-3 py-2 text-sm transition-colors',
      isSelected ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
    ].join(' ');

  const renderTab = (item: NavItem) => (
    <NavTab
      key={item.key}
      item={item}
      isActive={activeKey === item.key}
      badge={item.key === 'social' ? formatUnread(unread ?? 0) : undefined}
    />
  );

  return (
    // 56px, not the 48px this started at: the hover gestures are clipped by the
    // scroll track, and eight more pixels is what the tallest of them (the gem's
    // rotated diagonal) needs to play out whole. Anything past this and the bar
    // stops reading as a terminal chrome strip and starts eating the board.
    <header className="h-14 shrink-0 border-b border-line bg-surface flex items-center px-4 sticky top-0 z-50">
      <RealmSwitcher activeRealm={realmKey} />

      {/* The tabs sit centred in the bar rather than tucked against the logo.
          The centring lives on an inner `w-max mx-auto` track, not on
          `justify-center` on the scroller: with `justify-center`, once the tabs
          are wider than the bar the overflow spills equally in both directions
          and the first tab ends up scrolled out of reach on the left, with no
          way to scroll back to it. Auto margins collapse to zero at that point,
          so a narrow window simply falls back to the old left-aligned, fully
          scrollable row. */}
      <nav className="nav-scroll flex-1 min-w-0 h-full">
        <div className="flex items-center gap-1 h-full w-max mx-auto">
          {/* The Overview dropdown is spliced in at index 2 of the global set —
              which is what puts Macro directly beside the other market views.
              The BIST set has no such insertion: its own market views are
              already contiguous, so it renders straight through. */}
          {realmKey === 'global' ? (
            <>
              {navItems.slice(0, 2).map(renderTab)}

              <div
                ref={triggerRef}
                className="h-full"
                onMouseEnter={handleDropdownOpen}
                onMouseLeave={handleDropdownClose}
              >
                <Link
                  href="/overview?type=crypto"
                  className={NAV_TAB_CLASS}
                  data-active={isOverview}
                  data-nav="overview"
                  style={tintStyle('var(--nav-overview)')}
                >
                  <BarChart3 className="w-3.5 h-3.5" />
                  <span>Overview</span>
                  <ChevronDown
                    className={`w-3 h-3 transition-transform ${showDropdown ? 'rotate-180' : ''}`}
                  />
                </Link>

                {showDropdown && (
                  <div
                    className="fixed pt-1 z-50"
                    style={{ left: dropdownPos.left, top: dropdownPos.top }}
                  >
                    <div className="w-44 py-1 bg-surface border border-line rounded-lg">
                      <Link
                        href="/overview?type=crypto"
                        onClick={() => setShowDropdown(false)}
                        className={subItemClass(isOverview && overviewType === 'crypto')}
                      >
                        <Bitcoin className="w-3.5 h-3.5 text-data-btc" />
                        <span>Crypto</span>
                      </Link>
                      <Link
                        href="/overview?type=nasdaq"
                        onClick={() => setShowDropdown(false)}
                        className={subItemClass(isOverview && overviewType === 'nasdaq')}
                      >
                        <LineChart className="w-3.5 h-3.5 text-data-eth" />
                        <span>NASDAQ</span>
                      </Link>
                    </div>
                  </div>
                )}
              </div>

              {navItems.slice(2).map(renderTab)}
            </>
          ) : (
            navItems.map(renderTab)
          )}

          {adminSession?.is_admin && (
            <NavTab item={realm.adminItem} isActive={activeKey === realm.adminItem.key} />
          )}
        </div>
      </nav>

      {/* Right of the tabs, left of the health badge — chrome, not board. It
          used to be a panel on Macro and a card on Home and Overview; here it
          is one reading on every tab, at the size a novelty gauge earns. */}
      <div className="flex items-center gap-2 pl-3 shrink-0">
        {/* Alarms sit here rather than in the Chart panel's header: they cover
            every surface on the board now, not just a price on one chart. */}
        <AlarmBell />
        {/* One novelty gauge, whichever realm the reader is in. The Pentagon
            Pizza Index is about a building in Arlington and means nothing on a
            Borsa İstanbul board; the Gece Mesaisi Endeksi is about the Resmî
            Gazete and means nothing on a crypto board. They share the slot
            rather than stacking, so the header keeps its shape either way. */}
        {realmKey === 'bist' ? <NightShiftBadge /> : <PizzaIndexBadge />}
        <LiveStatusBadge />
      </div>
    </header>
  );
}
