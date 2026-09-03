'use client';

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { rollCaret, type Caret } from '@/lib/landing/caret';
/** The spine needs a number, a short name and somewhere to jump to. Nothing
 *  else — which is what lets the FAQ, whose sections are question groups rather
 *  than prose, drive the same rail. */
export interface RailItem {
  readonly id: string;
  readonly index: string;
  readonly label: string;
}

interface DocRailProps {
  sections: readonly RailItem[];
}

/** Where down the viewport the "you are here" line sits. */
const ACTIVE_LINE = 0.25;
/** Slack for fractional device pixels, so the bottom of the page is reachable. */
const BOTTOM_EPSILON = 2;

/**
 * The section spine, and a candle marking where you are.
 *
 * The marker is `.landing-caret` — the same glyph the typed lists write with.
 * That is not decoration for its own sake: the write head becomes the read head,
 * and crossing a section boundary rolls a fresh candle exactly as typing a
 * character does, so the page has one idea about what a cursor looks like.
 *
 * Hidden below `lg`. It is pure navigation, and every section it names is a
 * visible heading in the reading column — a collapsed "on this page" control on
 * a page this short would be more chrome than the page has content.
 */
export default function DocRail({ sections }: DocRailProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const [activeId, setActiveId] = useState<string>(sections[0]?.id ?? '');
  const [caret, setCaret] = useState<Caret | null>(null);
  const [top, setTop] = useState<number | null>(null);

  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>('[data-doc-section]'));
    if (nodes.length === 0) return;

    /**
     * Which section is being read, from geometry alone.
     *
     * This was an `IntersectionObserver` first, and the observer could not
     * answer three of the four cases on its own. It reports crossings, so it has
     * nothing to say about a page that opened already scrolled or on a deep
     * link; it goes quiet for as long as the reading line sits inside one long
     * section; and it never fires for the last section at all, because the page
     * runs out of scroll before that section top reaches the line — which left
     * the marker parked one row short at the bottom of every page.
     *
     * Eight rectangles per scroll frame, throttled to a frame, is cheaper than
     * carrying an observer plus the geometry needed to patch around it.
     */
    const pick = (): string => {
      const scroller = document.documentElement;
      // At the bottom there is no scroll left to bring the last section up to
      // the line, so reaching the end of the page *is* the signal.
      if (window.scrollY + window.innerHeight >= scroller.scrollHeight - BOTTOM_EPSILON) {
        return nodes[nodes.length - 1].id;
      }

      const line = window.innerHeight * ACTIVE_LINE;
      let found = nodes[0].id;
      for (const node of nodes) {
        if (node.getBoundingClientRect().top > line) break;
        found = node.id;
      }
      return found;
    };

    let frame = 0;
    const update = (): void => {
      frame = 0;
      setActiveId(pick());
    };

    const schedule = (): void => {
      if (frame) return;
      frame = requestAnimationFrame(update);
    };

    update();
    window.addEventListener('scroll', schedule, { passive: true });
    window.addEventListener('resize', schedule);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', schedule);
    };
  }, [sections]);

  // Position the marker against the active row, and print a new candle for it.
  // `useLayoutEffect` so the first placement happens before paint; the CSS
  // transition on `top` then carries every move after that.
  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const row = list.querySelector<HTMLElement>(`[data-row="${activeId}"]`);
    if (!row) return;
    setTop(row.offsetTop + row.offsetHeight / 2);
    setCaret(rollCaret());
  }, [activeId]);

  return (
    <nav aria-label="On this page" className="hidden lg:block">
      <div className="sticky top-[5.5rem] max-h-[calc(100svh-8rem)] overflow-y-auto nav-scroll">
        <ol ref={listRef} className="relative border-l border-dashed border-line pl-4">
          {sections.map((section) => {
            const active = section.id === activeId;
            return (
              <li key={section.id} data-row={section.id}>
                <a
                  href={`#${section.id}`}
                  aria-current={active ? 'true' : undefined}
                  className={`flex items-baseline gap-2.5 py-1.5 text-sm transition-colors ${
                    active ? 'text-fg' : 'text-fg-subtle hover:text-fg-muted'
                  }`}
                >
                  <span className="font-mono text-2xs tabnum">{section.index}</span>
                  <span>{section.label}</span>
                </a>
              </li>
            );
          })}

          {caret && top !== null && (
            <span
              aria-hidden="true"
              className="landing-caret landing-spine-mark"
              data-tone={caret.tone}
              style={
                {
                  left: -3,
                  top: top - 7,
                  '--caret-body-top': caret.bodyTop,
                  '--caret-body-height': caret.bodyHeight,
                } as CSSProperties
              }
            />
          )}
        </ol>
      </div>
    </nav>
  );
}
