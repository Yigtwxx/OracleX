'use client';

import { useEffect, useState } from 'react';

import { SESSION_LABEL, sessionState, type SessionState } from '@/lib/bist-format';

/**
 * Where the trading day is, in the marketing header.
 *
 * The BIST route suppresses the English section tabs and used to hand the
 * middle of the bar a bare spacer, so two thirds of the header was empty and
 * the page read as one whose navigation had not loaded. A board's header is a
 * status line, not a menu — and this is the one fact the page can state up
 * there without a request, since it is a clock rather than a quote.
 *
 * Resolved after mount. `sessionState` reads Istanbul time, the server renders
 * in whatever zone it is in, and a mismatch between the two is a hydration
 * error rather than a wrong label — so the slot holds its width and fills in.
 */
export default function SessionBadge() {
  const [state, setState] = useState<SessionState | null>(null);

  useEffect(() => {
    const sync = () => setState(sessionState());
    sync();
    // A minute is finer than the only boundaries that matter (10:00, 18:00).
    const timer = window.setInterval(sync, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="borsa-status min-w-0 flex-1">
      <span className="borsa-status-inner" data-state={state ?? undefined}>
        <span className="borsa-status-dot" aria-hidden="true" />
        <span className="borsa-status-label">{state ? SESSION_LABEL[state] : ' '}</span>
        <span className="borsa-status-sep" aria-hidden="true" />
        <span className="borsa-status-scope">BIST 100 · TEFAS · KAP</span>
      </span>
    </div>
  );
}
