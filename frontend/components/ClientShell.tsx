'use client';

import { Suspense, useEffect } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/lib/queryClient';
import BootGate from '@/components/BootGate';
import Navigation from '@/components/Navigation';
import GlobalTicker from '@/components/GlobalTicker';
import PriceAlertModal from '@/components/PriceAlertModal';
import ToastProvider from '@/components/ToastProvider';
import { usePriceAlerts } from '@/hooks/usePriceAlerts';

export default function ClientShell({ children }: { children: React.ReactNode }) {
  // Proof of life for the chunk-recovery watchdog in app/layout.tsx. This is
  // the outermost client component, so if this effect never runs, nothing in
  // the app is running — and a server-rendered boot splash with dead JS looks
  // exactly like a working one. The watchdog reloads on the difference.
  useEffect(() => {
    document.documentElement.setAttribute('data-hydrated', '1');
  }, []);

  // Initialize price alert monitoring globally
  usePriceAlerts();

  return (
    <QueryClientProvider client={queryClient}>
      {/* Nothing below mounts until the backend finishes warming up, so the app
          appears once and complete rather than filling in panel by panel. */}
      <BootGate>
        {/* Global decorative floor — see globals.css › APP BACKDROP. Rendered
            here rather than per page so it is drawn once and never scrolls. */}
        <div aria-hidden className="app-backdrop" />

        <div className="h-screen flex flex-col overflow-hidden">
          {/* Header Navigation — reads search params, so it needs a boundary */}
          {/* The fallback must match Navigation's own height exactly, or the
              whole board shifts up the moment the real bar swaps in. */}
          <Suspense fallback={<div className="h-14 shrink-0 border-b border-line bg-surface" />}>
            <Navigation />
          </Suspense>

          {/* Global Ticker Tape */}
          <GlobalTicker />

          {/* Page Content */}
          <main className="flex-1 min-h-0 overflow-hidden">{children}</main>

          {/* Global Price Alert Modal */}
          <PriceAlertModal />
        </div>
      </BootGate>

      {/* Global Toast Notifications */}
      <ToastProvider />
    </QueryClientProvider>
  );
}
