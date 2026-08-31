'use client';

import { useParams } from 'next/navigation';

import BistFundDetailPage from '@/components/bist/BistFundDetailPage';

export default function BistFundDetailRoute() {
  const params = useParams<{ kod: string }>();
  return <BistFundDetailPage code={params.kod} />;
}
