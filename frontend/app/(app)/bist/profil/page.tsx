'use client';

import { Suspense } from 'react';

import ProfilePage from '@/components/ProfilePage';

/**
 * The same page as `/profile`, mounted inside the BIST realm.
 *
 * Not a redirect and not a copy, for the reason `/bist/admin` already carries:
 * the header reads the realm off the path, so opening settings from a Borsa
 * İstanbul board on the global route swapped the whole tab set to Kripto /
 * Nasdaq under the reader. Two addresses for one component is what keeps them
 * where they were.
 *
 * The Suspense boundary is not optional here either — ProfilePage reads `?tab=`
 * through useSearchParams, which opts the route into client-side rendering, and
 * without a boundary the production build fails rather than degrading.
 */
export default function BistProfileRoute() {
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
