'use client';

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { rollCaret, type Caret } from '@/lib/landing/caret';

/**
 * Milliseconds per character.
 *
 * Set against the scroll rather than against what a person types: the panel is
 * on screen for about a screen and a half, and a list still writing itself when
 * the reader has scrolled past it is a list nobody read. Four lines land in
 * roughly six seconds, which fits inside that window.
 */
const CHAR_MS = 30;

/** Rest at the end of a line before the caret drops to the next one. */
const LINE_PAUSE_MS = 220;

/** The frame budget, so a backgrounded tab does not fast-forward on return. */
const MAX_FRAME_MS = 64;

interface TypedPointsProps {
  items: readonly string[];
  /** Applied to the list. */
  className?: string;
  /** Applied to every row. */
  itemClassName?: string;
}

/**
 * The `›` lists, written out a character at a time once the card is on screen.
 *
 * Nothing is reserved. A row does not exist until its first character does, and
 * a row that exists is exactly as wide as what has been written into it — so
 * the list grows out of the panel rather than filling in a grid of blanks that
 * were sitting there waiting. The panel grows with it, which is why the effect
 * is gated on the list being properly on screen: the growth has to happen where
 * it reads as the terminal writing, not as the page settling.
 *
 * Two details are load-bearing and neither is obvious from the effect:
 *
 * The caret is `position: absolute` with no offsets, so it renders at its static
 * position — exactly where it would sit in the flow — while contributing no box.
 * An in-flow inline-block would be an atomic inline, which gives the browser a
 * line-break opportunity right at the write head: the last word would hop to the
 * next line and back as the caret moved through it.
 *
 * The half-written list is hidden from assistive technology and a complete copy
 * is exposed beside it, for the seconds the animation lasts. A screen reader
 * that arrived mid-write would otherwise be handed sentences that stop partway,
 * and there is no state in which that is the content.
 */
export default function TypedPoints({
  items,
  className = '',
  itemClassName = '',
}: TypedPointsProps) {
  const ref = useRef<HTMLUListElement>(null);

  /** Characters written across the whole list; `null` means "all of them". */
  const [typed, setTyped] = useState<number | null>(null);
  const [caret, setCaret] = useState<Caret | null>(null);

  /** The moment each character is due, in milliseconds from the first one. */
  const schedule = useMemo(() => {
    const due: number[] = [];
    let t = 0;
    for (const item of items) {
      for (let i = 0; i < item.length; i += 1) {
        t += CHAR_MS;
        due.push(t);
      }
      t += LINE_PAUSE_MS;
    }
    return due;
  }, [items]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let raf = 0;
    let elapsed = 0;
    let last = 0;
    let written = 0;

    const finish = (): void => {
      cancelAnimationFrame(raf);
      raf = 0;
      setTyped(null);
      setCaret(null);
    };

    const step = (now: number): void => {
      elapsed += last === 0 ? 16 : Math.min(now - last, MAX_FRAME_MS);
      last = now;

      let next = written;
      while (next < schedule.length && schedule[next] <= elapsed) next += 1;
      if (next >= schedule.length) {
        finish();
        return;
      }

      // One candle per character, not one per frame. The roll belongs to the
      // character, so it has to be gated on the character count changing —
      // rolling every frame turns a tape into a strobe, and the slower the
      // typing the worse it gets, which is the opposite of what slowing it down
      // is for.
      if (next !== written) {
        written = next;
        setTyped(written);
        setCaret(rollCaret());
      }
      raf = requestAnimationFrame(step);
    };

    const start = (): void => {
      if (raf || motion.matches) return;
      last = 0;
      // The first character's candle, so the caret is on the line from the
      // first frame rather than arriving one character late.
      setCaret(rollCaret());
      raf = requestAnimationFrame(step);
    };

    // Reduced motion gets the finished list. So does anything the page loaded
    // already scrolled past: an IntersectionObserver only reports crossings, so
    // a restored scroll position never intersects and would leave the list
    // blank for good — the same case `Reveal` has to handle by hand.
    if (motion.matches || node.getBoundingClientRect().bottom < 0) return;

    setTyped(0);

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        start();
      },
      { rootMargin: '-12% 0px -20% 0px' }
    );
    observer.observe(node);

    const onMotionChange = (): void => {
      if (motion.matches) finish();
    };
    motion.addEventListener('change', onMotionChange);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      motion.removeEventListener('change', onMotionChange);
    };
  }, [schedule]);

  // How much of each row is written, and which row the caret is on.
  //
  // The caret claims a row while `typed` is still *at* its last character, not
  // past it, so it parks at the end of a finished line for the pause and only
  // then drops to the next one. That is what a terminal does, and it is what
  // makes the pause read as deliberate rather than as a stall.
  const written: number[] = [];
  let caretRow = -1;
  let consumed = 0;
  for (const item of items) {
    if (typed === null) {
      written.push(item.length);
      continue;
    }
    written.push(Math.max(0, Math.min(typed - consumed, item.length)));
    if (caretRow === -1 && typed <= consumed + item.length) caretRow = written.length - 1;
    consumed += item.length;
  }

  const typing = typed !== null;

  return (
    <>
      <ul ref={ref} className={className} aria-hidden={typing || undefined}>
        {items.map((item, i) => {
          // Rows past the caret are not rendered at all. Rendered-but-empty
          // rows are a column of chevrons pointing at nothing, which reads as
          // the list failing to load rather than as it being written.
          if (typing && i > caretRow) return null;

          return (
            <li key={item} className={itemClassName}>
              <span aria-hidden="true" className="mt-px font-mono text-accent">
                ›
              </span>
              <span>
                {item.slice(0, written[i])}
                {caret && i === caretRow && (
                  <span
                    className="landing-caret"
                    data-tone={caret.tone}
                    style={
                      {
                        '--caret-body-top': caret.bodyTop,
                        '--caret-body-height': caret.bodyHeight,
                      } as CSSProperties
                    }
                  />
                )}
              </span>
            </li>
          );
        })}
      </ul>

      {typing && (
        <ul className="sr-only">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </>
  );
}
