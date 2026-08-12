'use client';

import { useEffect, useState } from 'react';
import BootSplash from '@/components/BootSplash';
import { useReadiness } from '@/hooks/useReadiness';

/**
 * Marks that this tab has already seen the backend come up. Scoped to the
 * session rather than the page, so client-side navigation never re-gates, and
 * scoped to the tab rather than localStorage, so a genuinely cold backend still
 * shows the splash the next time the app is opened.
 */
const SESSION_KEY = 'oracle-x:booted';

function alreadyBooted(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.sessionStorage.getItem(SESSION_KEY) === '1';
  } catch {
    // Private browsing modes can throw on sessionStorage access. Gating again
    // is a small cost; crashing the shell is not.
    return false;
  }
}

/**
 * Holds the app back until the backend reports itself ready.
 *
 * `children` are not merely hidden but never mounted, so no page-level query
 * fires against a backend that is still warming up — which is the whole point:
 * the screen appears once, complete, instead of assembling itself panel by
 * panel over the half-minute the backend needs from cold.
 */
export default function BootGate({ children }: { children: React.ReactNode }) {
  // Starts closed on the server and on first paint, then opens immediately if
  // this tab has booted before. Reading sessionStorage during render would
  // desync server and client HTML, so it happens in an effect.
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (alreadyBooted()) setOpen(true);
    setChecked(true);
  }, []);

  const { snapshot, ready, unreachable, retry } = useReadiness(checked && !open);

  useEffect(() => {
    if (!ready) return;
    try {
      window.sessionStorage.setItem(SESSION_KEY, '1');
    } catch {
      // Non-fatal: the gate simply re-runs on the next navigation.
    }
    setOpen(true);
  }, [ready]);

  if (open) return <>{children}</>;

  return <BootSplash snapshot={snapshot} failed={unreachable} onRetry={retry} />;
}
