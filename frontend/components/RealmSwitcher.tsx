'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

import Logo from '@/components/ui/Logo';
import { REALM_ICONS } from '@/components/nav-icons';
import { REALMS, realmFor, type RealmKey } from '@/lib/nav-items';

/** Matches the Overview dropdown's grace period, so the two feel like one bar. */
const CLOSE_DELAY_MS = 200;

interface RealmSwitcherProps {
  activeRealm: RealmKey;
  /**
   * Which side of the app the switcher is standing on.
   *
   * The menu offers the same two realms either way, but a reader on a product
   * page expects the other realm's product page, not to be dropped into a
   * terminal they have not opened yet. One control, two destinations.
   */
  surface?: 'terminal' | 'marketing';
  /** Layout hook for the header this sits in; the two bars space it differently. */
  className?: string;
}

/**
 * The mark in the top-left corner, and the menu that hangs off it.
 *
 * The mark is the realm switcher; the "Oracle-X" wordmark beside it stays a
 * plain link to `/`. Splitting them keeps the one behaviour this header has
 * always had — the logo is the way back out to the landing page — while giving
 * the switcher the affordance it needs. Collapsing both into one control would
 * have meant either losing the exit or hiding it behind a menu item.
 *
 * Opens on hover, like every other menu in this bar, but is a real button
 * underneath: hover alone is unreachable by keyboard, and this is now the only
 * route between two halves of the app.
 *
 * The quarter turn is CSS, keyed off `data-realm-open` — same contract the
 * fourteen nav icon gestures use (see globals.css). No transform is set from
 * JS, so `prefers-reduced-motion` can drop it without the component knowing.
 */
export default function RealmSwitcher({
  activeRealm,
  surface = 'terminal',
  className = 'pr-4',
}: RealmSwitcherProps) {
  const triggerId = useId();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  const closeTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);

  const close = () => {
    clearTimeout(closeTimeoutRef.current);
    closeTimeoutRef.current = undefined;
    setOpen(false);
  };

  const openNow = () => {
    clearTimeout(closeTimeoutRef.current);
    closeTimeoutRef.current = undefined;
    // Fixed, measured against the trigger, for the same reason the Overview
    // menu is: the nav track's `overflow-x` forces `overflow-y` to clip, so an
    // absolutely positioned menu is sliced off at the 56px header.
    const rect = triggerRef.current?.getBoundingClientRect();
    if (rect) setPosition({ left: rect.left, top: rect.bottom });
    setOpen(true);
  };

  const scheduleClose = () => {
    closeTimeoutRef.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  };

  // Clearing on unmount as well as on close: without it a timer armed by the
  // pointer leaving on the way to a navigation fires into a dead component.
  useEffect(() => () => clearTimeout(closeTimeoutRef.current), []);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const focusItem = (index: number) => {
    const items = itemRefs.current.filter(Boolean);
    if (items.length === 0) return;
    // Wraps both ways: two entries, so "down" from the last one is the only
    // sensible way back to the first without reaching for Home/End.
    const wrapped = (index + items.length) % items.length;
    items[wrapped]?.focus();
  };

  const onTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      openNow();
      // After paint, or the anchors do not exist yet to receive focus.
      requestAnimationFrame(() => focusItem(0));
    }
  };

  const onItemKeyDown = (event: React.KeyboardEvent<HTMLAnchorElement>, index: number) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      focusItem(index + 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      focusItem(index - 1);
    } else if (event.key === 'Tab') {
      // Tabbing out of the menu is a dismissal, not a trap: this is a two-item
      // switcher in a header, not a dialog.
      setOpen(false);
    }
  };

  return (
    <div
      ref={containerRef}
      className={`flex shrink-0 items-center gap-2 ${className}`}
      onMouseEnter={openNow}
      onMouseLeave={scheduleClose}
    >
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-label={realmFor(activeRealm).copy.switcher}
        aria-haspopup="menu"
        aria-expanded={open}
        // The hook the quarter turn hangs off. On the trigger rather than the
        // svg so the rule can also reach the chevron.
        data-realm-open={open}
        onClick={() => (open ? close() : openNow())}
        onKeyDown={onTriggerKeyDown}
        className="realm-trigger flex items-center gap-1.5 rounded-md px-1 py-1 text-fg transition-colors hover:text-accent focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
      >
        <span className="realm-mark flex">
          <Logo size={18} className="shrink-0" />
        </span>
        <ChevronDown className="realm-chevron h-3 w-3 text-fg-subtle" />
      </button>

      {/* The marketing page, not the terminal home: the wordmark has always
          been the way back out, and the tabs are how you move around inside.
          Which marketing page depends on the realm — leaving the BIST terminal
          should land on the BIST product page, not on the crypto one. */}
      <Link
        href={realmFor(activeRealm).marketingHref}
        className="whitespace-nowrap text-md font-semibold tracking-tight text-fg transition-colors hover:text-accent"
      >
        Oracle-X
      </Link>

      {open && (
        <div className="fixed z-50 pt-1" style={{ left: position.left, top: position.top }}>
          <div
            role="menu"
            // Labelled by the trigger rather than by a string of its own: the
            // trigger's name is already realm-aware, and a second literal here
            // would be a fifth phrase to keep translated for no extra meaning.
            aria-labelledby={triggerId}
            className="w-64 rounded-lg border border-line bg-surface py-1"
          >
            {REALMS.map((realm, index) => {
              const isActive = realm.key === activeRealm;
              return (
                <Link
                  key={realm.key}
                  ref={(node) => {
                    itemRefs.current[index] = node;
                  }}
                  href={surface === 'marketing' ? realm.marketingHref : realm.href}
                  role="menuitem"
                  aria-current={isActive ? 'true' : undefined}
                  onClick={close}
                  onKeyDown={(event) => onItemKeyDown(event, index)}
                  className={[
                    'flex w-full items-start gap-2.5 px-3 py-2 text-sm transition-colors',
                    isActive
                      ? 'bg-surface-2 text-fg'
                      : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
                  ].join(' ')}
                >
                  <span className="mt-0.5 flex shrink-0 items-center gap-1">
                    {REALM_ICONS[realm.key].map(({ icon: Icon, className }, iconIndex) => (
                      <Icon key={iconIndex} className={`h-3.5 w-3.5 ${className}`} />
                    ))}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{realm.label}</span>
                    <span className="block truncate text-2xs text-fg-subtle">
                      {realm.description}
                    </span>
                  </span>
                  {isActive && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />}
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
