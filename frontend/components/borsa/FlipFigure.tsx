'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * A figure that turns over into its second reading.
 *
 * The page's one recurring object. Borsa İstanbul's floor board and every
 * departure board the reader has stood under share a mechanism: a number does
 * not fade into another number, it *flips*, and the flip is what tells you the
 * old value was withdrawn rather than adjusted. That is exactly the claim here
 * — the nominal figure is not a smaller version of the real one, it is a
 * different statement — so the transition carries the argument instead of
 * decorating it.
 *
 * Character-level rather than digit-level: `+%31,5` and `%-0,2` do not share a
 * digit layout, and a flip that only turns the numerals would leave the sign
 * and the separator hanging still while the rest of the board moves.
 *
 * Plays once, on entry, and then holds. A figure that re-flips on every scroll
 * past reads as a widget; this one is a statement being corrected.
 */

/** Rendered when a slot exists on one face and not the other. */
const PAD = ' ';

/** Per-character stagger. The board sweeps left to right, as a board does. */
const STEP_MS = 45;

function pad(text: string, length: number): string {
  return text.length >= length ? text : PAD.repeat(length - text.length) + text;
}

export default function FlipFigure({
  from,
  to,
  fromColor,
  toColor,
  className = '',
  delayMs = 0,
  label,
}: {
  /** The claim, as every other site prints it. */
  from: string;
  /** What the page prints instead. */
  to: string;
  fromColor?: string;
  toColor?: string;
  className?: string;
  delayMs?: number;
  /** Accessible text. Screen readers get this instead of the split characters. */
  label: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [played, setPlayed] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    // Reduced motion lands on the end state directly. The correction is the
    // point; removing the animation must never remove the corrected value.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setPlayed(true);
      return;
    }

    // Already scrolled past on a restored position: show the result rather than
    // holding a stale claim on screen until the reader scrolls back up.
    if (node.getBoundingClientRect().bottom < 0) {
      setPlayed(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setPlayed(true);
        observer.disconnect();
      },
      { rootMargin: '-10% 0px -15% 0px' }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const width = Math.max(from.length, to.length);
  const outFace = pad(from, width);
  const inFace = pad(to, width);

  return (
    <span ref={ref} className={`borsa-flip ${className}`} data-played={played ? '' : undefined}>
      <span className="sr-only">{label}</span>
      <span aria-hidden="true" className="borsa-flip-board">
        {Array.from({ length: width }, (_, index) => (
          <span
            key={index}
            className="borsa-flip-char"
            style={{ ['--flip-delay' as string]: `${delayMs + index * STEP_MS}ms` }}
          >
            <span className="borsa-flip-out" style={fromColor ? { color: fromColor } : undefined}>
              {outFace[index]}
            </span>
            <span className="borsa-flip-in" style={toColor ? { color: toColor } : undefined}>
              {inFace[index]}
            </span>
          </span>
        ))}
      </span>
    </span>
  );
}
