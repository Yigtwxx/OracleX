'use client';

import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  /** Optional custom fallback. Receives the error and a reset callback. */
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Reusable error boundary for wrapping individual widgets/sections so a single
 * crashing component doesn't blank the whole page. For full-page errors prefer
 * the route-level `app/error.tsx`.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, info);
  }

  reset = () => this.setState({ hasError: false, error: null });

  render() {
    const { hasError, error } = this.state;
    if (hasError && error) {
      if (this.props.fallback) return this.props.fallback(error, this.reset);
      return (
        <div className="surface flex flex-col items-center justify-center gap-3 p-6 text-center">
          <AlertTriangle className="h-5 w-5 text-down" aria-hidden="true" />
          <p className="text-base text-fg-muted">Something went wrong loading this section.</p>
          <button
            type="button"
            onClick={this.reset}
            className="inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:text-fg hover:border-line-strong"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
