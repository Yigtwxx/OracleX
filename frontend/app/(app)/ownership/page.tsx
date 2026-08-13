'use client';

import { Suspense } from 'react';
import OwnershipPage from '@/components/OwnershipPage';

// The Suspense boundary is required, not decorative: OwnershipPage reads
// `useSearchParams`, and App Router refuses to statically prerender a client
// component that does so without one.
export default function Page() {
  return (
    <Suspense fallback={<div className="shimmer h-full" />}>
      <OwnershipPage />
    </Suspense>
  );
}
