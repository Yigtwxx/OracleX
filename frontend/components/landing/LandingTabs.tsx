'use client';

import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MARKETING_TABS } from '@/lib/marketing/tabs';

/**
 * `Navigation`'s tab class, minus the two things that only make sense there.
 *
 * The app bar draws its active state as a per-tab bottom border, which is why
 * its rows are a pixel taller than the header and pulled back up by a negative
 * margin. Here the underline is one element that slides, so the rows need
 * neither. What is kept is the shape: same height, same padding, same
 * `whitespace-nowrap shrink-0` so an overflowing row scrolls rather than wraps.
 */
const TAB_CLASS =
  'landing-tab flex h-full items-center px-2 text-sm font-medium transition-colors whitespace-nowrap shrink-0 sm:px-3 sm:text-base';

interface Bar {
  readonly left: number;
  readonly width: number;
}

/**
 * The marketing sections, in the middle of the landing header.
 *
 * The underline is measured rather than declared. Its position comes from the
 * active tab's own box, which is the only thing that survives a font swap: the
 * mono and sans faces load after first paint and change every tab's width, so a
 * bar positioned once at mount ends up several pixels off and stays there. A
 * `ResizeObserver` on the row catches that, and the viewport changes with it.
 *
 * `usePathname` rather than `useSearchParams` on purpose — the latter forces a
 * Suspense boundary and opts the whole route out of static generation, for a
 * value this component has no use for.
 */
export default function LandingTabs() {
  const pathname = usePathname();
  const rowRef = useRef<HTMLDivElement>(null);
  const [bar, setBar] = useState<Bar | null>(null);

  const measure = useCallback((): void => {
    const row = rowRef.current;
    if (!row) return;
    const active = row.querySelector<HTMLElement>('[data-active="true"]');
    if (!active) {
      setBar(null);
      return;
    }
    setBar({ left: active.offsetLeft, width: active.offsetWidth });
  }, []);

  useLayoutEffect(() => {
    measure();

    const row = rowRef.current;
    if (!row) return;
    const observer = new ResizeObserver(measure);
    observer.observe(row);
    for (const child of Array.from(row.children)) observer.observe(child);

    return () => observer.disconnect();
  }, [measure, pathname]);

  return (
    <nav aria-label="Sections" className="nav-scroll h-full min-w-0 flex-1">
      <div ref={rowRef} className="relative mx-auto flex h-full w-max items-center">
        {MARKETING_TABS.map((tab) => {
          // Exact match, not `startsWith`: `/` is a prefix of every route, and
          // a prefix test would light the first tab on all three pages.
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={TAB_CLASS}
              data-active={active}
              aria-current={active ? 'page' : undefined}
            >
              {tab.label}
            </Link>
          );
        })}

        <span
          aria-hidden="true"
          className="landing-tab-underline"
          data-ready={bar ? '' : undefined}
          style={bar ? { left: bar.left, width: bar.width } : undefined}
        />
      </div>
    </nav>
  );
}
