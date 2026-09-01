'use client';

import { Suspense } from 'react';

import BistSmartMoneyPage from '@/components/bist/BistSmartMoneyPage';

// The Suspense boundary is required, not decorative: the page keeps its
// cross-filter in the URL and therefore reads `useSearchParams`, and App Router
// refuses to statically prerender a client component that does so without one.
export default function BistSmartMoneyRoute() {
  return (
    <Suspense fallback={<div className="shimmer h-full" />}>
      <BistSmartMoneyPage />
    </Suspense>
  );
}
