'use client';

import { MarketOverview } from '@/lib/api';
import { formatLargeNumber } from './overview-utils';

interface BottomStatsGridProps {
  marketData: MarketOverview | null;
  marketType: 'crypto' | 'nasdaq';
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="surface p-4">
      <div className="label">{label}</div>
      <p className="mt-2 text-xl font-mono tabnum text-fg">{value}</p>
    </div>
  );
}

export default function BottomStatsGrid({ marketData, marketType }: BottomStatsGridProps) {
  const isNasdaq = marketType === 'nasdaq';

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Stat
        label="Total Market Cap"
        value={marketData ? formatLargeNumber(marketData.total_market_cap) : '--'}
      />
      <Stat
        label="24h Volume"
        value={marketData ? formatLargeNumber(marketData.total_volume_24h) : '--'}
      />
      <Stat
        label={isNasdaq ? 'Tech Weight' : 'BTC Dominance'}
        value={isNasdaq ? 'N/A' : marketData ? `${marketData.btc_dominance.toFixed(1)}%` : '--'}
      />
      <Stat
        label={isNasdaq ? 'Active Stocks' : 'Active Cryptocurrencies'}
        value={marketData ? marketData.active_cryptocurrencies.toLocaleString('en-US') : '--'}
      />
    </div>
  );
}
