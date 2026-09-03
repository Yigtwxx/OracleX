'use client';

import { QueryClient, QueryCache, MutationCache } from '@tanstack/react-query';

let toastCallback: ((message: string) => void) | null = null;

export function setToastCallback(cb: (message: string) => void) {
  toastCallback = cb;
}

/**
 * Show an error toast from imperative (non-React-Query) code paths.
 *
 * Prefer letting React Query surface errors via its cache handlers below; use
 * this only where a component handles an action's failure itself. No-ops until
 * ToastProvider has mounted and registered its callback.
 */
export function showToast(message: string) {
  toastCallback?.(message);
}

let alarmToastCallback: ((message: string) => void) | null = null;

/**
 * Register the alarm channel. Separate from `setToastCallback` because that one
 * is hardwired to raise errors — routing an alarm through it would render a
 * fired alarm as a failure.
 */
export function setAlarmToastCallback(cb: (message: string) => void) {
  alarmToastCallback = cb;
}

/** Announce a fired alarm in-app. No-ops until ToastProvider has mounted. */
export function showAlarmToast(message: string) {
  alarmToastCallback?.(message);
}

/**
 * Opt a query or mutation out of the global error toast by setting
 * `meta: { silentError: true }`. Use it where the caller shows a message of its
 * own — otherwise the user gets two toasts for one failure.
 */
type ErrorMeta = { silentError?: boolean } | undefined;

function handleGlobalError(error: unknown, meta?: ErrorMeta) {
  const message = error instanceof Error ? error.message : 'Bir hata oluştu';
  console.error('[QueryClient Error]', message);
  if (meta?.silentError) return;
  toastCallback?.(`Bağlantı hatası — ${message}`);
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => handleGlobalError(error, query.meta as ErrorMeta),
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) =>
      handleGlobalError(error, mutation.options.meta as ErrorMeta),
  }),
  defaultOptions: {
    queries: {
      retry: 3,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
      staleTime: 30 * 1000, // 30 seconds default
      gcTime: 5 * 60 * 1000, // 5 minutes garbage collection
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
    mutations: {
      retry: 1,
    },
  },
});
