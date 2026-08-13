'use client';

import { useEffect } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * Route-level error boundary (Next.js App Router convention). Catches render
 * errors thrown by page components and shows a recoverable fallback while the
 * surrounding layout (navigation, ticker) stays intact.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Page error:', error);
  }, [error]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
      <AlertTriangle className="h-6 w-6 text-down" aria-hidden="true" />
      <h2 className="text-lg font-semibold text-fg">Something went wrong</h2>
      <p className="max-w-md text-base text-fg-muted">
        An unexpected error occurred while loading this page. You can try again or come back later.
      </p>
      <button
        type="button"
        onClick={reset}
        className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90"
      >
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Try again
      </button>
    </div>
  );
}
