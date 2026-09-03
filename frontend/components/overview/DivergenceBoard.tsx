'use client';

import { useMemo, useState } from 'react';
import { TrendingDown, TrendingUp } from 'lucide-react';
import { CoinData, MarketOverview } from '@/lib/api';
import { findDivergences } from '@/lib/market-breadth';
import AssetDetailModal from './AssetDetailModal';
import AssetLogo from '@/components/ui/AssetLogo';

interface DivergenceBoardProps {
  marketData: MarketOverview | null;
  marketType: 'crypto' | 'nasdaq';
  isLoading: boolean;
}

const signed = (value: number): string => `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;

function Column({
  title,
  subtitle,
  icon: Icon,
  tone,
  rows,
  marketType,
  onSelectAsset,
}: {
  title: string;
  subtitle: string;
  icon: typeof TrendingUp;
  tone: 'up' | 'down';
  rows: CoinData[];
  marketType: 'crypto' | 'nasdaq';
  onSelectAsset: (symbol: string) => void;
}) {
  return (
    <div className="surface p-4">
      <div className="flex items-center gap-2">
        <Icon className={`w-3.5 h-3.5 ${tone === 'up' ? 'text-up' : 'text-down'}`} />
        <h3 className="label">{title}</h3>
      </div>
      <p className="mt-1 text-2xs text-fg-subtle">{subtitle}</p>

      {rows.length === 0 ? (
        // Nothing here is a real reading: it means the tape and the week agree
        // everywhere, which is worth saying rather than leaving a blank card.
        <p className="mt-4 text-sm text-fg-subtle">Nothing is moving against its week right now.</p>
      ) : (
        <div className="mt-3">
          <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 pb-1.5 border-b border-line">
            <span className="label">Asset</span>
            <span className="label text-right w-[62px]">24h</span>
            <span className="label text-right w-[62px]">7d</span>
          </div>

          {rows.map((coin) => (
            <button
              key={coin.symbol}
              type="button"
              onClick={() => onSelectAsset(coin.symbol)}
              className="w-full grid grid-cols-[1fr_auto_auto] gap-x-3 items-center py-2 border-b border-line last:border-b-0 text-left hover:bg-surface-2 transition-colors rounded-sm"
            >
              <span className="flex items-center gap-2 min-w-0">
                <AssetLogo
                  symbol={coin.symbol}
                  providedLogo={coin.logo}
                  marketType={marketType}
                  size={40}
                  className="w-5 h-5 rounded-full object-cover bg-surface-2 shrink-0"
                />
                <span className="text-base text-fg truncate">{coin.symbol}</span>
              </span>
              <span
                className={`text-sm font-mono tabnum text-right w-[62px] ${
                  coin.change_24h >= 0 ? 'text-up' : 'text-down'
                }`}
              >
                {signed(coin.change_24h)}
              </span>
              <span
                className={`text-sm font-mono tabnum text-right w-[62px] ${
                  (coin.change_7d ?? 0) >= 0 ? 'text-up' : 'text-down'
                }`}
              >
                {signed(coin.change_7d ?? 0)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {[0, 1].map((i) => (
        <div key={i} className="surface p-4 space-y-2.5">
          <div className="h-2.5 w-36 rounded bg-surface-2 shimmer" />
          {[0, 1, 2].map((r) => (
            <div key={r} className="h-5 w-full rounded bg-surface-2 shimmer" />
          ))}
        </div>
      ))}
    </div>
  );
}

/**
 * Assets whose day contradicts their week.
 *
 * Not a second Gainers/Losers card: those rank by today alone, and today's
 * biggest gainer is usually just continuing a run. This ranks the assets where
 * the two horizons disagree, which is the only place on the page `change_7d`
 * is read at all despite arriving on every row of the payload.
 */
export default function DivergenceBoard({
  marketData,
  marketType,
  isLoading,
}: DivergenceBoardProps) {
  const [selectedAsset, setSelectedAsset] = useState<string | undefined>(undefined);

  const { reversing, fading } = useMemo(
    () => findDivergences(marketData?.coins ?? []),
    [marketData]
  );

  const hasWeekly = useMemo(
    () => (marketData?.coins ?? []).some((c) => typeof c.change_7d === 'number'),
    [marketData]
  );

  if (isLoading && !marketData) return <Skeleton />;
  // Without a weekly series there is no second horizon to diverge from, and an
  // empty two-column board would read as "no divergence" rather than "no data".
  if (!marketData || !hasWeekly) return null;

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Column
          title="Up today, down on the week"
          subtitle="Attempting a turn after a weak week"
          icon={TrendingUp}
          tone="up"
          rows={reversing}
          marketType={marketType}
          onSelectAsset={setSelectedAsset}
        />
        <Column
          title="Down today, up on the week"
          subtitle="Giving back a strong week"
          icon={TrendingDown}
          tone="down"
          rows={fading}
          marketType={marketType}
          onSelectAsset={setSelectedAsset}
        />
      </div>

      {selectedAsset && (
        <AssetDetailModal
          symbol={selectedAsset}
          marketType={marketType}
          onClose={() => setSelectedAsset(undefined)}
        />
      )}
    </>
  );
}
