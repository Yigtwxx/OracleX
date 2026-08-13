'use client';

import { useEffect } from 'react';

/**
 * Proof of life for the chunk-recovery watchdog in app/layout.tsx. This is the
 * outermost client component, so if this effect never runs, nothing in the app
 * is running — and a server-rendered page with dead JS looks exactly like a
 * working one. The watchdog reloads on the difference.
 *
 * Lives in the root layout rather than inside ClientShell because the marketing
 * route group deliberately renders without the shell; without this the landing
 * page would fail the watchdog's check and reload itself every 30 seconds.
 */
export default function HydrationBeacon() {
  useEffect(() => {
    document.documentElement.setAttribute('data-hydrated', '1');
  }, []);

  return null;
}
