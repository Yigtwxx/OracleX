import {
  BarChart3,
  Bitcoin,
  Blocks,
  BrainCircuit,
  Building2,
  CalendarDays,
  CandlestickChart,
  Crosshair,
  Gauge,
  Gem,
  Home,
  Hourglass,
  Landmark,
  Layers,
  LayoutDashboard,
  LayoutGrid,
  LineChart,
  Megaphone,
  MessageCircleMore,
  MessagesSquare,
  PieChart,
  Radar,
  Radio,
  ShieldAlert,
  User,
  Users,
} from 'lucide-react';
import type { ComponentType } from 'react';

import PolymarketMark from '@/components/ui/PolymarketMark';
import type { NavKey, RealmKey } from '@/lib/nav-items';

/**
 * The glyph for every tab, and for the two realms in the logo menu.
 *
 * Separate from `lib/nav-items.ts` because that module is held to the same
 * rule as the rest of `lib/` — pure, importable by the vitest suite, free of
 * React. A component import there is what breaks `npm test`, since Next's
 * tsconfig sets `jsx: "preserve"` and the runner leaves JSX untransformed.
 *
 * Completeness is a type, not a test: `Record<NavKey, …>` means a tab added to
 * the union without a glyph here fails `tsc --noEmit`, which is a CI gate. A
 * runtime lookup with a fallback would have rendered a blank tab instead.
 */
export type NavIcon = ComponentType<{ className?: string }>;

export const NAV_ICONS: Record<NavKey, NavIcon> = {
  home: Home,
  dashboard: LayoutDashboard,
  macro: Gem,
  // Polymarket's own mark — see components/ui/PolymarketMark.
  polymarket: PolymarketMark,
  live: Radio,
  // Not `Boxes`, whose eleven children are mush at 14px, and not `Layers`,
  // which Heatmap already owns. `Blocks` is two elements, and the pair is the
  // subject: a chain, and the block about to join it. The hover gesture in
  // globals.css is built on exactly that split.
  chains: Blocks,
  ownership: Landmark,
  analysis: BrainCircuit,
  // MessageCircleMore, not MessageCircle: same bubble path, plus the three
  // dots the typing gesture animates. Swapping back silently removes it.
  chat: MessageCircleMore,
  derivatives: Layers,
  community: Users,
  // MessagesSquare, not MessageCircleMore — that bubble belongs to Chat, and
  // two tabs sharing a glyph is two tabs nobody can tell apart at 14px.
  social: MessagesSquare,
  profile: User,
  // ShieldAlert rather than Shield: its first path is the same shield, and the
  // two it adds are the exclamation the hover gesture draws inside it. Hidden
  // at rest by globals.css, so this still reads as a plain shield until pointed
  // at. Swapping back to Shield silently removes the gesture.
  admin: ShieldAlert,

  'bist-overview': Gauge,
  'bist-stocks': CandlestickChart,
  // LayoutGrid is the treemap's own shape — nested rectangles of unequal size.
  // Distinct from the candlesticks next to it and from Layers, which the global
  // realm's derivatives tab already holds.
  'bist-heatmap': LayoutGrid,
  // PieChart rather than a chart line: what a reader actually compares between
  // two TEFAS funds is the portfolio split, not the NAV curve.
  'bist-funds': PieChart,
  // Radar, because the tab is about detecting someone else's position rather
  // than holding one: which funds moved into a name, what the settlement
  // ratios say, who is short.
  'bist-smart-money': Radar,
  'bist-kap': Megaphone,
  // Hourglass is the literal subject: VIOP contracts are "vadeli" — what
  // separates them from the spot board is that they expire.
  'bist-viop': Hourglass,
  // Layers, because the page is literally two of them on one axis: the
  // futures book and the spot volume profile.
  // A building rather than a second pie: Fonlar already owns the pie, and two
  // tabs with one glyph are two tabs nobody tells apart at a glance.
  'bist-ownership': Building2,
  'bist-viop-map': Layers,
  // Crosshair, not Radar: Konumlanma already owns the radar dish, and the
  // subject here is a single name lined up at a level rather than a sweep.
  'bist-radar': Crosshair,
  'bist-macro': Landmark,
};

export interface RealmIcon {
  icon: NavIcon;
  /** A fixed colour rather than a realm tint: the global realm's entry is the
      same two-tone Bitcoin/LineChart pair the Overview dropdown already uses,
      and the recognition comes from the pairing rather than from one hue. */
  className: string;
}

export const REALM_ICONS: Record<RealmKey, RealmIcon[]> = {
  global: [
    { icon: Bitcoin, className: 'text-data-btc' },
    { icon: LineChart, className: 'text-data-eth' },
  ],
  bist: [{ icon: BarChart3, className: 'text-[color:var(--nav-bist-overview)]' }],
};
