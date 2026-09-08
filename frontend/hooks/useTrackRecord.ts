'use client';

import { useEffect, useState } from 'react';
import { API_BASE_URL } from '@/lib/api';
import type { TrackRecordSummary } from '@/lib/trackRecord';

export interface TrackRecordState {
  summary: TrackRecordSummary | undefined;
  loading: boolean;
  /** True when the backend could not be reached or answered a failure. */
  unreachable: boolean;
}

/**
 * Fetch the accuracy board once.
 *
 * Deliberately not polled and not React Query. The record moves when the hourly
 * scoring job closes a horizon, so a poll would re-fetch an unchanged board all
 * day; and the shared query client raises a toast from its global `onError`,
 * which on a public marketing page would put an application error in front of a
 * reader who has not signed in.
 *
 * A failure leaves `summary` undefined rather than substituting an empty board.
 * Zeros here would read as "the model got nothing right", which is a claim, not
 * a loading state.
 */
export function useTrackRecord(): TrackRecordState {
  const [summary, setSummary] = useState<TrackRecordSummary | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const load = async (): Promise<void> => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/track-record/summary`, {
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json()) as TrackRecordSummary;
        if (cancelled) return;
        setSummary(data);
        setUnreachable(false);
      } catch {
        if (cancelled) return;
        setUnreachable(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { summary, loading, unreachable };
}
