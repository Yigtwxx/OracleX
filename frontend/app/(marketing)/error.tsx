'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * Landing-page error boundary. Separate from (app)/error.tsx because that one
 * uses `h-full`, which resolves to zero outside ClientShell's flex `main`.
 */
export default function MarketingError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Landing page error:', error);
  }, [error]);

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-8 text-center">
      <AlertTriangle className="h-6 w-6 text-down" aria-hidden="true" />
      <h1 className="text-xl font-semibold text-fg">Something went wrong</h1>
      <p className="max-w-md text-base text-fg-muted">
        The landing page failed to load. You can try again, or head straight into the terminal.
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-base text-accent-fg transition-opacity hover:opacity-90"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          Try again
        </button>
        <Link
          href="/home"
          className="inline-flex items-center rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          Go terminal
        </Link>
      </div>
    </div>
  );
}
