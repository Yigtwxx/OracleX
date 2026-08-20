'use client';

import { useState, useRef, type CSSProperties } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
import {
  LayoutDashboard,
  BarChart3,
  Blocks,
  ChevronDown,
  Bitcoin,
  LineChart,
  MessageCircleMore,
  MessagesSquare,
  Home,
  Landmark,
  Layers,
  Gem,
  Radio,
  User,
  BrainCircuit,
  Users,
  ShieldAlert,
} from 'lucide-react';
import Logo from '@/components/ui/Logo';
import LiveStatusBadge from '@/components/LiveStatusBadge';
import PizzaIndexBadge from '@/components/PizzaIndexBadge';
import { useIsAdmin } from '@/hooks/useAdmin';
import { useUnreadCount } from '@/hooks/useSocial';
import { formatUnread } from '@/lib/social';

interface NavItem {
  key: string;
  href: string;
  label: string;
  icon: typeof Home;
  /** The tab's hue, as a `var(--nav-*)` reference rather than a Tailwind class.
      `.nav-tab` reads it out of `--nav-tint` for the icon, the label and the
      active underline; a class per state would have needed three verbatim
      literals per tab, since Tailwind cannot generate `hover:text-nav-${key}`. */
  tint: string;
  /** Heatmap only: the label carries the board's own yellow→orange→red ramp,
      which no single token can express. See `.nav-heat-label` in globals.css. */
  labelClass?: string;
}

const NAV_ITEMS: NavItem[] = [
  // '/home', not '/': the root is the marketing landing page, which lives
  // outside this shell entirely.
  { key: 'home', href: '/home', label: 'Home', icon: Home, tint: 'var(--nav-home)' },
  {
    key: 'dashboard',
    href: '/dashboard',
    label: 'Dashboard',
    icon: LayoutDashboard,
    tint: 'var(--nav-dashboard)',
  },
  // Index 2 is not cosmetic: the bar renders slice(0, 2), then the Overview
  // dropdown, then slice(2) — so this is what puts Macro directly beside the
  // other market views rather than out past Chat.
  { key: 'macro', href: '/macro', label: 'Macro', icon: Gem, tint: 'var(--nav-macro)' },
  // Beside Macro rather than out past Chat: the two answer the same question a
  // beat apart — Macro is what the world looks like, Live is what is happening
  // to it right now.
  { key: 'live', href: '/live', label: 'Live', icon: Radio, tint: 'var(--nav-live)' },
  // Directly after Live, which continues the run rather than starting a new one:
  // Macro is what the world looks like, Live is what is happening to it, and
  // this is the state of the rails underneath while it does. Placing it here
  // also keeps the market views contiguous — Overview through Chains — instead
  // of leaving Ownership between them.
  //
  // Not `Boxes`, whose eleven children are mush at 14px, and not `Layers`,
  // which Heatmap already owns. `Blocks` is two elements, and the pair is the
  // subject: a chain, and the block about to join it. The hover gesture in
  // globals.css is built on exactly that split.
  { key: 'chains', href: '/chains', label: 'Chains', icon: Blocks, tint: 'var(--nav-chains)' },
  {
    key: 'ownership',
    href: '/ownership',
    label: 'Ownership',
    icon: Landmark,
    tint: 'var(--nav-ownership)',
  },
  {
    key: 'analysis',
    href: '/analysis',
    label: 'Analysis',
    icon: BrainCircuit,
    tint: 'var(--nav-analysis)',
  },
  {
    key: 'chat',
    href: '/chat',
    label: 'Chat',
    // MessageCircleMore, not MessageCircle: same bubble path, plus the three
    // dots the typing gesture animates. Swapping back silently removes it.
    icon: MessageCircleMore,
    tint: 'var(--nav-chat)',
  },
  {
    key: 'heatmap',
    href: '/heatmap',
    label: 'Heatmap',
    icon: Layers,
    tint: 'var(--nav-heatmap-2)',
    labelClass: 'nav-heat-label',
  },
  {
    key: 'community',
    href: '/community',
    label: 'Community',
    icon: Users,
    tint: 'var(--nav-community)',
  },
  // Between Community and Profile because that is the order of the question it
  // answers: the board is everyone, this is the people on it, Profile is you.
  {
    key: 'social',
    href: '/social',
    label: 'Social',
    // MessagesSquare, not MessageCircleMore — that bubble belongs to Chat, and
    // two tabs sharing a glyph is two tabs nobody can tell apart at 14px.
    icon: MessagesSquare,
    tint: 'var(--nav-social)',
  },
  { key: 'profile', href: '/profile', label: 'Profile', icon: User, tint: 'var(--nav-profile)' },
];

// Kept out of NAV_ITEMS because it is conditional: only an admin ever sees it.
// The tab is cosmetic — /admin renders "does not exist" and every route behind
// it 403s — but there is no reason to show a door nobody else can open.
const ADMIN_ITEM: NavItem = {
  key: 'admin',
  href: '/admin',
  label: 'Admin',
  // ShieldAlert rather than Shield: its first path is the same shield, and the
  // two it adds are the exclamation the hover gesture draws inside it. Hidden
  // at rest by globals.css, so this still reads as a plain shield until pointed
  // at. Swapping back to Shield silently removes the gesture.
  icon: ShieldAlert,
  tint: 'var(--nav-admin)',
};

const DROPDOWN_CLOSE_DELAY_MS = 200;

function resolveActiveKey(pathname: string): string {
  // Matched against the admin item too, or /admin would light up Home.
  const match = [...NAV_ITEMS, ADMIN_ITEM].find((item) => pathname.startsWith(item.href));
  if (match) return match.key;
  if (pathname.startsWith('/overview')) return 'overview';
  return 'home';
}

// No colour classes here: `.nav-tab` owns the rest / hover / active colours so
// that one `--nav-tint` per item drives all three (see globals.css).
// Height derived from the track rather than repeated as a literal, so the bar's
// height lives in exactly one place — the header. The extra pixel is what pairs
// with `-mb-px`: the tab reaches one pixel past the track, onto the header's own
// bottom border, and the negative margin keeps that pixel from growing the row.
// At a flat `h-full` the two cancel to a half-pixel offset and the active
// underline sits just shy of the header line instead of on it.
const NAV_TAB_CLASS = [
  'nav-tab flex items-center gap-2 h-[calc(100%_+_1px)] px-3 text-sm font-medium transition-colors whitespace-nowrap shrink-0',
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
  const { key, href, label, icon: Icon, tint, labelClass } = item;
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

  const activeKey = resolveActiveKey(pathname);
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

  return (
    // 56px, not the 48px this started at: the hover gestures are clipped by the
    // scroll track, and eight more pixels is what the tallest of them (the gem's
    // rotated diagonal) needs to play out whole. Anything past this and the bar
    // stops reading as a terminal chrome strip and starts eating the board.
    <header className="h-14 shrink-0 border-b border-line bg-surface flex items-center px-4 sticky top-0 z-50">
      {/* '/', not '/home': the logo is the way back out to the landing page.
          The terminal itself is reachable from the nav tabs. */}
      <Link href="/" className="flex items-center gap-2 pr-4 shrink-0">
        <Logo size={18} className="text-fg shrink-0" />
        <span className="text-md font-semibold tracking-tight text-fg whitespace-nowrap">
          Oracle-X
        </span>
      </Link>

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
          {NAV_ITEMS.slice(0, 2).map((item) => (
            <NavTab
              key={item.key}
              item={item}
              isActive={activeKey === item.key}
              badge={item.key === 'social' ? formatUnread(unread ?? 0) : undefined}
            />
          ))}

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

          {NAV_ITEMS.slice(2).map((item) => (
            <NavTab
              key={item.key}
              item={item}
              isActive={activeKey === item.key}
              badge={item.key === 'social' ? formatUnread(unread ?? 0) : undefined}
            />
          ))}

          {adminSession?.is_admin && (
            <NavTab item={ADMIN_ITEM} isActive={activeKey === ADMIN_ITEM.key} />
          )}
        </div>
      </nav>

      {/* Right of the tabs, left of the health badge — chrome, not board. It
          used to be a panel on Macro and a card on Home and Overview; here it
          is one reading on every tab, at the size a novelty gauge earns. */}
      <div className="flex items-center gap-2 pl-3 shrink-0">
        <PizzaIndexBadge />
        <LiveStatusBadge />
      </div>
    </header>
  );
}
