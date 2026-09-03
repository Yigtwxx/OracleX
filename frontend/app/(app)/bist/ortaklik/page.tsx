'use client';

import { Suspense } from 'react';

import BistOwnershipPage from '@/components/bist/ownership/BistOwnershipPage';

// The Suspense boundary is required, not decorative: the page keeps its view
// in the URL and therefore reads `useSearchParams`, and App Router refuses to
// statically prerender a client component that does so without one.
export default function BistOwnershipRoute() {
  return (
    <Suspense fallback={<div className="shimmer h-full" />}>
      <BistOwnershipPage />
    </Suspense>
  );
}
