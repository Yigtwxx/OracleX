'use client';

import { useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '@/lib/api';

/** How often the badge asks the backend for the current board. */
const POLL_INTERVAL_MS = 10_000;

export type SourceState = 'ok' | 'degraded' | 'down' | 'idle';
export type OverallStatus = 'live' | 'degraded' | 'offline' | 'starting';

export interface HealthCategory {
  key: string;
  label: string;
  /** Losing this makes the app wrong rather than thinner — it turns the badge red. */
  critical: boolean;
  providers: string[];
  state: SourceState;
  /** Unix seconds of the last successful call, or null if there has not been one. */
  last_ok_at: number | null;
  latency_ms: number | null;
  /** Short failure class, never a URL or an upstream body. Null while healthy. */
  detail: string | null;
}

export interface HealthSnapshot {
  status: OverallStatus;
  generated_at: number;
  categories: HealthCategory[];
}

export interface SystemHealth {
  snapshot: HealthSnapshot | undefined;
  /** What the badge shows. `offline` also covers "the backend itself did not answer". */
  status: OverallStatus;
  /** True when the API could not be reached at all, as opposed to reporting a fault. */
  unreachable: boolean;
}

/**
 * Poll the backend's data-source health for the LIVE badge.
 *
 * Deliberately not React Query, for the same reason as `useReadiness`: the
 * shared query client raises a toast from its global `onError`, and a failed
 * poll here is exactly the condition the badge exists to display. Surfacing it
 * twice — once as a red badge, once as an error toast — would be noise.
 *
 * Polling pauses while the tab is hidden. A background tab has no one watching
 * the badge, and browsers throttle its timers anyway, so the requests would buy
 * nothing but a stale answer on return.
 */
export function useSystemHealth(): SystemHealth {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | undefined>(undefined);
  const [unreachable, setUnreachable] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;

    const schedule = (): void => {
      timerRef.current = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };

    const poll = async (): Promise<void> => {
      if (cancelled) return;

      // Nothing to show and nobody to show it to: resume on the next visibility
      // change rather than burning a request per interval in the background.
      if (typeof document !== 'undefined' && document.hidden) {
        schedule();
        return;
      }

      try {
        const response = await fetch(`${API_BASE_URL}/api/system/health`, {
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json()) as HealthSnapshot;
        if (cancelled) return;
        setSnapshot(data);
        setUnreachable(false);
      } catch {
        if (cancelled) return;
        // Keep the last board on screen so the panel can still say what was
        // working before contact was lost; the badge alone reports the outage.
        setUnreachable(true);
      }

      schedule();
    };

    void poll();

    const onVisible = (): void => {
      if (document.hidden) return;
      if (timerRef.current) clearTimeout(timerRef.current);
      void poll();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  return {
    snapshot,
    status: unreachable ? 'offline' : (snapshot?.status ?? 'starting'),
    unreachable,
  };
}
