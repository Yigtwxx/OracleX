'use client';

import { useParams } from 'next/navigation';

import BistStockDetailPage from '@/components/bist/BistStockDetailPage';

export default function BistStockDetailRoute() {
  const params = useParams<{ ticker: string }>();
  return <BistStockDetailPage ticker={params.ticker} />;
}
