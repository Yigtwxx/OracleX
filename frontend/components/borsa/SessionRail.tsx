'use client';

import { useEffect, useRef } from 'react';

/** Borsa İstanbul's continuous auction, in minutes past midnight. */
const OPEN_MINUTES = 10 * 60;
const CLOSE_MINUTES = 18 * 60;

const MARKS = [10, 12, 14, 16, 18].map((hour) => ({
  hour,
  label: `${String(hour).padStart(2, '0')}:00`,
  fraction: (hour * 60 - OPEN_MINUTES) / (CLOSE_MINUTES - OPEN_MINUTES),
}));

/**
 * A trading session, read as a scrollbar.
 *
 * Borsa İstanbul opens at 10:00 and closes at 18:00. The crypto board this app
 * was built for never closes at all, and that is the real difference between
 * the two products rather than a difference in what they plot — so this page is
 * scaled to one session and the rail says how far through it you have read.
 *
 * Written straight to the DOM inside a rAF rather than held in state: this
 * updates on every scroll frame, and a re-render per frame would be a re-render
 * of the whole page for two inline styles.
 */
export default function SessionRail() {
  const fillRef = useRef<HTMLSpanElement>(null);
  const tickRef = useRef<HTMLSpanElement>(null);
  const barRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let frame = 0;

    const update = () => {
      frame = 0;
      const scrollable = document.documentElement.scrollHeight - window.innerHeight;
      // A page shorter than the viewport has no progress to report; showing a
      // full rail there would claim the session had closed.
      const progress = scrollable > 0 ? Math.min(1, Math.max(0, window.scrollY / scrollable)) : 0;
      const percent = `${(progress * 100).toFixed(2)}%`;
      if (fillRef.current) fillRef.current.style.height = percent;
      if (tickRef.current) tickRef.current.style.top = percent;
      if (barRef.current) barRef.current.style.width = percent;
    };

    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(update);
    };

    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  return (
    // aria-hidden: it reports reading progress, which the scrollbar already
    // tells assistive technology. Announcing a clock that is not a clock would
    // be worse than silence.
    <div aria-hidden="true">
      <div className="borsa-rail">
        <span ref={fillRef} className="borsa-rail-fill" style={{ height: '0%' }} />
        <span ref={tickRef} className="borsa-rail-tick" style={{ top: '0%' }} />
        {MARKS.map((mark) => (
          <span
            key={mark.hour}
            className="borsa-rail-time borsa-label"
            style={{ top: `${mark.fraction * 100}%` }}
          >
            {mark.label}
          </span>
        ))}
      </div>

      {/* Below lg there is no margin to hang a vertical rail in, and the device
          that cannot show it used to lose the page's signature device entirely.
          The same session, laid on its side under the header, costs one more
          element and keeps the metaphor on a phone. */}
      <div className="borsa-rail-bar">
        <span ref={barRef} className="borsa-rail-bar-fill" style={{ width: '0%' }} />
      </div>
    </div>
  );
}
