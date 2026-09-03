'use client';

import { useEffect, useState } from 'react';
import Logo from '@/components/ui/Logo';

/** Long enough to cover a font swap, short enough not to read as a stall. */
const FONT_GRACE_MS = 1200;
/** Absolute ceiling. The cover comes off even if the scene never reports. */
const MAX_HOLD_MS = 2600;

interface LandingGateProps {
  /** True once the canvas has painted a frame. */
  sceneReady: boolean;
}

/**
 * Holds the page behind an opaque cover until the scene is actually running.
 *
 * This belongs to `/` alone. The other marketing routes render through
 * `MarketingChrome`, which does not mount it: they are complete in the server
 * HTML, so there is nothing for a cover to hide and no canvas to report ready —
 * the gate would simply black them out until `MAX_HOLD_MS` expired.
 *
 * The landing page is server-rendered, so the copy and the empty board are on
 * screen well before the bundle that drives the canvas is. Scrolling in that
 * window scrolls a dead page — the tape does not print, the annotations do not
 * arrive — and the first thing the page does is fail to answer. The cover ships
 * in the server HTML and the scroll lock is a plain CSS rule (see
 * `.landing-gate` in globals.css) rather than something JS applies, because the
 * window being closed here is precisely the one before any JS runs.
 *
 * Both timers are ceilings, not schedules. Nothing may leave the page covered:
 * a canvas that never reports and a font that never resolves both release on
 * their own. If the bundle never arrives at all the cover stays, which is the
 * same failure the chunk watchdog in `app/layout.tsx` already reloads on.
 */
export default function LandingGate({ sceneReady }: LandingGateProps) {
  const [released, setReleased] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setReleased(true), MAX_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!sceneReady) return;

    // Fonts as well as the canvas: the panels, the price scale and the board
    // are set in the mono face, and releasing mid-swap shows the page reflowing
    // — which is the settling the cover exists to hide.
    let live = true;
    const release = (): void => {
      if (live) setReleased(true);
    };
    void document.fonts.ready.then(release);
    const timer = window.setTimeout(release, FONT_GRACE_MS);

    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [sceneReady]);

  return (
    <div className="landing-gate" data-hold={released ? undefined : ''} aria-hidden>
      <div className="landing-gate-mark">
        <Logo size={22} className="text-fg-muted" />
        <span className="font-mono text-2xs uppercase tracking-[0.14em] text-fg-subtle">
          Loading market data
        </span>
      </div>
    </div>
  );
}
