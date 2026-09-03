'use client';

import { LucideIcon } from 'lucide-react';
import AssetLogo from '@/components/ui/AssetLogo';

interface AssetListItem {
  symbol: string;
  logo?: string;
  change_24h: number;
}

interface AssetListCardProps {
  title: string;
  icon: LucideIcon;
  data: AssetListItem[];
  isLoading: boolean;
  marketType: 'crypto' | 'nasdaq';
  /** Only `trending` shows rank numbers; the rest are ordered by change. */
  type: 'trending' | 'gainer' | 'loser';
}

export default function AssetListCard({
  title,
  icon: Icon,
  data,
  isLoading,
  marketType,
  type,
}: AssetListCardProps) {
  return (
    <div className="surface p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-3.5 h-3.5 text-fg-muted" />
        <h3 className="label">{title}</h3>
      </div>

      <div className="space-y-2">
        {isLoading
          ? [0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="w-5 h-5 rounded-full bg-surface-2 shimmer" />
                <div className="flex-1 h-4 rounded bg-surface-2 shimmer" />
              </div>
            ))
          : data.map((asset, i) => (
              <div key={asset.symbol} className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  {type === 'trending' && (
                    <span className="w-3 text-2xs font-mono tabnum text-fg-subtle">{i + 1}</span>
                  )}
                  <AssetLogo
                    symbol={asset.symbol}
                    providedLogo={asset.logo}
                    marketType={marketType}
                    size={40}
                    className="w-5 h-5 rounded-full object-cover bg-surface-2"
                  />
                  <span className="text-base text-fg truncate">{asset.symbol}</span>
                </div>
                <span
                  className={`text-sm font-mono tabnum ${asset.change_24h >= 0 ? 'text-up' : 'text-down'}`}
                >
                  {asset.change_24h >= 0 ? '+' : ''}
                  {asset.change_24h.toFixed(2)}%
                </span>
              </div>
            ))}
      </div>
    </div>
  );
}
