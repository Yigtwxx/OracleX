'use client';

import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, RotateCw } from 'lucide-react';
import './globals.css';

/**
 * The chunk watchdog's cooldown stamp — see the recovery script in
 * `app/layout.tsx`. Clearing it is part of retrying: the watchdog holds off for
 * 30s after a reload so a genuinely missing chunk cannot loop forever, but an
 * explicit retry is the user saying to try again anyway.
 */
const CHUNK_COOLDOWN_KEY = 'oracle-x:chunk-reload';

/**
 * Root error boundary (Next.js App Router convention).
 *
 * `app/error.tsx` only catches renders *below* the root layout, so anything the
 * layout itself throws — a provider reading missing env, for one — takes the
 * whole client tree down with nothing to catch it, leaving the server-rendered
 * boot splash frozen on screen with no way forward. This is that missing net,
 * and it replaces the layout entirely, hence its own `<html>`/`<body>` and its
 * own stylesheet import.
 *
 * Styled to match `BootSplash`, since that is the screen it most often replaces.
 *
 * Note the absent `reset`. Next.js hands one to every error boundary, but at
 * this level it re-renders the same root layout out of the same chunks that
 * just failed — so it throws straight back into this screen and the button
 * reads as dead. What actually recovers a failed boot is what the user ends up
 * doing by hand: a reload. So that is what the button does.
 */
export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  const [reloading, setReloading] = useState(false);

  useEffect(() => {
    console.error('Application error:', error);
  }, [error]);

  const handleRetry = useCallback(() => {
    setReloading(true);
    try {
      window.sessionStorage.removeItem(CHUNK_COOLDOWN_KEY);
    } catch {
      // Private browsing can throw here. The reload below is the part that
      // matters and does not depend on it.
    }
    window.location.reload();
  }, []);

  return (
    <html lang="en">
      <body className="font-sans text-base antialiased">
        <div className="h-screen w-screen flex items-center justify-center bg-bg px-6">
          <div className="w-full max-w-sm text-center">
            <h1 className="text-sm font-semibold tracking-[0.2em] text-fg mb-8">ORACLE-X</h1>
            <AlertTriangle className="w-5 h-5 text-warn mx-auto mb-3" aria-hidden />
            <p className="text-base text-fg mb-1">Uygulama başlatılamadı</p>
            <p className="text-xs text-fg-subtle mb-5">
              Beklenmeyen bir hata oluştu. Ayrıntı için konsolu kontrol edin.
            </p>
            <button
              type="button"
              onClick={handleRetry}
              disabled={reloading}
              className="inline-flex items-center gap-2 px-3 py-1.5 text-base bg-surface border border-line rounded-md text-fg-muted hover:text-fg hover:border-line-strong transition-colors disabled:cursor-wait disabled:opacity-60"
            >
              <RotateCw className={`w-3.5 h-3.5 ${reloading ? 'animate-spin' : ''}`} aria-hidden />
              {reloading ? 'Yeniden yükleniyor…' : 'Tekrar dene'}
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
