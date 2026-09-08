'use client';

import { Liquidation } from '@/lib/api';
import { AlertCircle, TrendingDown, TrendingUp } from 'lucide-react';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';

interface LiquidationFeedProps {
  data: Liquidation[];
  isLoading: boolean;
  isError: boolean;
}

export default function LiquidationFeed({ data, isLoading, isError }: LiquidationFeedProps) {
  if (isLoading) return <PanelSkeleton />;

  const hasRows = !isError && data.length > 0;

  return (
    <Panel
      title="Liquidations"
      /* The Live badge is a claim about the feed, not about the panel. Over an
         empty body it asserts a silent market, which is exactly the reading a
         failed request must not be given. */
      action={
        hasRows ? (
          <span className="flex items-center gap-1.5 text-xs text-fg-subtle">
            <span className="w-1.5 h-1.5 rounded-full bg-up live-indicator" />
            Live
          </span>
        ) : undefined
      }
      footnote="Long liquidated = forced sell · Short liquidated = forced buy"
    >
      {isError ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          <span className="text-base">Liquidations unavailable</span>
        </div>
      ) : data.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          <span className="text-base">No liquidations in the window</span>
        </div>
      ) : (
        <div className="divide-y divide-line">
          {data.map((item, index) => {
            // A liquidated long means price dropped.
            const isLongLiq = item.side === 'Long';

            return (
              <div
                key={`${item.symbol}-${item.timestamp}-${index}`}
                className="px-4 py-2.5 hover:bg-surface-2 transition-colors flex items-center justify-between gap-3"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {isLongLiq ? (
                    <TrendingDown className="w-3.5 h-3.5 shrink-0 text-down" />
                  ) : (
                    <TrendingUp className="w-3.5 h-3.5 shrink-0 text-up" />
                  )}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-base text-fg">{item.symbol}</span>
                      <span
                        className={`text-2xs px-1.5 py-px rounded ${isLongLiq ? 'bg-down-bg text-down' : 'bg-up-bg text-up'}`}
                      >
                        {item.side}
                      </span>
                    </div>
                    <div className="text-xs font-mono tabnum text-fg-subtle">
                      @ ${item.price.toLocaleString('en-US')}
                    </div>
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <div className="text-base font-mono tabnum text-fg">
                    $
                    {item.amount_usd.toLocaleString('en-US', {
                      maximumFractionDigits: 0,
                    })}
                  </div>
                  <div className="text-xs text-fg-subtle">{item.time_ago}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
