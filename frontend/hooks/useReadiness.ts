'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '@/lib/api';

/** How often the boot gate asks the backend how far along it is. */
const POLL_INTERVAL_MS = 500;

/**
 * How long the backend may stay unreachable before the gate reports an outage.
 *
 * Measured as a duration, not a count of polls: five failures at a 500ms
 * interval gave the backend 2.3 seconds to start accepting connections, and the
 * app is normally launched with the backend starting at the same moment. Every
 * cold start therefore opened on the error screen, and a refresh a few seconds
 * later "fixed" it — the backend had simply finished booting by then.
 *
 * A connection refusal rejects instantly, so this budget is spent almost
 * entirely on waiting rather than on the requests themselves.
 */
const UNREACHABLE_AFTER_MS = 25_000;

/**
 * Ceiling on how long the gate polls before giving up and showing the app.
 * The backend has a deadline of its own; this covers the case where it never
 * answers at all, so a misconfigured API URL cannot lock the user out.
 */
const GATE_TIMEOUT_MS = 90_000;

export type StepState = 'pending' | 'running' | 'ok' | 'failed';

export interface ReadinessStep {
  key: string;
  label: string;
  required: boolean;
  state: StepState;
  /** Wall-clock time the step took, or null while it is still running. */
  duration_ms: number | null;
  /** Short reason a step failed, or null. Never a raw upstream body. */
  error: string | null;
}

export interface ReadinessSnapshot {
  ready: boolean;
  /** Ready, but something did not work — the splash marks which step. */
  degraded: boolean;
  /** A required step failed outright; polling longer will not help. */
  blocked: boolean;
  elapsed_ms: number;
  deadline_ms: number;
  steps: ReadinessStep[];
}

export interface Readiness {
  snapshot: ReadinessSnapshot | undefined;
  /** True once the app may be shown, whether cleanly or degraded. */
  ready: boolean;
  /** The backend could not be reached, or a required step failed. */
  unreachable: boolean;
  /** Discard the failure state and start polling again. */
  retry: () => void;
}

/**
 * Poll the backend's startup progress.
 *
 * Deliberately not React Query: the shared query client raises an error toast
 * from its global `onError`, and a poll against a backend that is still booting
 * fails by design. Those failures are this hook's normal input, not incidents.
 */
export function useReadiness(enabled: boolean): Readiness {
  const [snapshot, setSnapshot] = useState<ReadinessSnapshot | undefined>(undefined);
  const [unreachable, setUnreachable] = useState(false);
  const [attempt, setAttempt] = useState(0);

  /** When the current run of consecutive failures started, or null if healthy. */
  const failingSinceRef = useRef<number | null>(null);

  const retry = useCallback(() => {
    failingSinceRef.current = null;
    setUnreachable(false);
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();

    const poll = async (): Promise<void> => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/system/readiness`, {
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = (await response.json()) as ReadinessSnapshot;
        if (cancelled) return;

        failingSinceRef.current = null;
        setSnapshot(data);

        // A failed required step is terminal: the backend has finished trying,
        // so keep the error on screen instead of polling a settled answer.
        if (data.ready || data.blocked) return;
      } catch {
        if (cancelled) return;
        const now = Date.now();
        if (failingSinceRef.current === null) failingSinceRef.current = now;
        if (now - failingSinceRef.current >= UNREACHABLE_AFTER_MS) {
          setUnreachable(true);
          return;
        }
      }

      if (Date.now() - startedAt > GATE_TIMEOUT_MS) {
        // Never trap the user behind the splash because of the gate itself.
        setUnreachable(true);
        return;
      }

      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, attempt]);

  return {
    snapshot,
    ready: snapshot?.ready ?? false,
    unreachable: unreachable || (snapshot?.blocked ?? false),
    retry,
  };
}
