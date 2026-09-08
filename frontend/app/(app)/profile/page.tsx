'use client';

import { Suspense } from 'react';

import ProfilePage from '@/components/ProfilePage';

export default function ProfileRoute() {
  // ProfilePage reads `?tab=` through useSearchParams, which opts the route into
  // client-side rendering; without a boundary here the production build fails
  // rather than degrading. The fallback matches the page's own auth-loading
  // shimmer so the two are indistinguishable.
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center p-6">
          <div className="surface shimmer h-40 w-full max-w-sm" />
        </div>
      }
    >
      <ProfilePage />
    </Suspense>
  );
}
