'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import OverviewPage from '@/components/OverviewPage';

function OverviewContent() {
  const searchParams = useSearchParams();
  const marketType = (searchParams.get('type') as 'crypto' | 'nasdaq') || 'crypto';

  return <OverviewPage marketType={marketType} />;
}

export default function OverviewRoute() {
  return (
    <Suspense
      fallback={
        <div className="flex-1 flex items-center justify-center">
          <div className="text-base text-fg-subtle">Loading…</div>
        </div>
      }
    >
      <OverviewContent />
    </Suspense>
  );
}
