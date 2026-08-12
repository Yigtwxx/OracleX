'use client';

import { useEffect, useState } from 'react';

/**
 * A ticking clock, shared by everything on a page that counts down.
 *
 * The Live tab renders a countdown on every row, and giving each row its own
 * interval would mean forty timers waking the tab independently. One timer at
 * the top, its value passed down as a prop, keeps the whole page on a single
 * heartbeat — and makes the countdowns tick in step, which they visibly do not
 * when each row owns its own.
 */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return now;
}
