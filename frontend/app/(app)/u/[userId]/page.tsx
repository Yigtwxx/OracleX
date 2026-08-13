'use client';

import { useParams } from 'next/navigation';

import PublicProfilePage from '@/components/profile/PublicProfilePage';

export default function PublicProfileRoute() {
  const params = useParams<{ userId: string }>();
  return <PublicProfilePage userId={params.userId} />;
}
