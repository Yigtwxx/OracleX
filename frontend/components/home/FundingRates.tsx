'use client';

import { useEffect, useState } from 'react';
import { FundingRate } from '@/lib/api';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';

interface FundingRatesProps {
  data: FundingRate[];
  isLoading: boolean;
}

function useCountdown(nextFundingTimeMs: number | undefined) {
  const [timeLeft, setTimeLeft] = useState('');

  useEffect(() => {
    if (!nextFundingTimeMs) {
      setTimeLeft('--:--');
      return;
    }

    const update = () => {
      const diff = nextFundingTimeMs - Date.now();
      if (diff <= 0) {
        setTimeLeft('0m');
        return;
      }
      const hours = Math.floor(diff / 3600000);
      const minutes = Math.floor((diff % 3600000) / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      setTimeLeft(
        `${hours}h ${minutes.toString().padStart(2, '0')}m ${seconds.toString().padStart(2, '0')}s`
      );
    };

    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [nextFundingTimeMs]);

  return timeLeft;
}

export default function FundingRates({ data, isLoading }: FundingRatesProps) {
  // 4h and 8h perpetuals are mixed in the same table, so their settlement times
  // differ — the header counts down to whichever lands first.
  const nextFunding = data.length
    ? Math.min(...data.map((item) => item.next_funding_time))
    : undefined;
  const countdown = useCountdown(nextFunding);

  if (isLoading) return <PanelSkeleton />;

  return (
    <Panel
      title="Funding Rates"
      action={
        <span className="text-xs text-fg-subtle">
          Next funding <span className="font-mono tabnum text-fg-muted">{countdown}</span>
        </span>
      }
      footnote="Positive rate: longs pay shorts (bullish sentiment) · Est. APR extrapolates the current rate · Extreme: |rate| ≥ 0.05%"
      /* Column widths are declared once here and mirrored on the rows below.
         They have to be explicit: the header sits outside the scroll container
         (see `Panel`), so a table's automatic column sizing can no longer reach
         across the two and keep them aligned. */
      columns={
        <div className="flex items-center gap-3 px-4 py-1.5 bg-surface-2">
          <span className="label flex-1 min-w-0">Symbol</span>
          <span className="label w-[152px] shrink-0 text-right">Rate</span>
          <span className="label w-20 shrink-0 text-right">Est. APR</span>
        </div>
      }
    >
      <div>
        {/* Backend orders this: the fixed core block by market cap, then any
            outlier that cleared the extreme threshold, by funding intensity. */}
        {data.map((item) => {
          const isPositive = item.rate > 0;
          // Saturates just past the 0.05% extreme threshold, so an outlier
          // reads as a full bar while ordinary rates stay visibly short.
          const intensity = Math.min(Math.abs(item.rate) * 20000, 100);

          return (
            <div
              key={item.symbol}
              className="flex items-center gap-3 px-4 py-2 border-t border-line hover:bg-surface-2 transition-colors"
            >
              <span className="flex-1 min-w-0 flex items-center gap-2">
                <span className="text-base text-fg">{item.symbol}</span>
                {item.is_extreme && (
                  <span
                    className={`text-2xs px-1.5 py-px rounded ${isPositive ? 'bg-up-bg text-up' : 'bg-down-bg text-down'}`}
                  >
                    EXTREME
                  </span>
                )}
              </span>
              <span className="w-[152px] shrink-0 flex items-center justify-end gap-2">
                {/* The rate is per settlement period, and those differ by pair. */}
                <span className="text-2xs font-mono tabnum text-fg-subtle">
                  {item.interval_hours}h
                </span>
                <span
                  className={`text-base font-mono tabnum ${isPositive ? 'text-up' : 'text-down'}`}
                >
                  {item.rate_formatted}
                </span>
                <span className="w-12 h-1 bg-line rounded-full overflow-hidden">
                  <span
                    className={`block h-full ${isPositive ? 'bg-up' : 'bg-down'}`}
                    style={{
                      width: `${intensity}%`,
                      marginLeft: isPositive ? '0' : 'auto',
                    }}
                  />
                </span>
              </span>
              {/* Not a quoted APR — the current rate held constant for a year. */}
              <span className="w-20 shrink-0 text-right text-base font-mono tabnum text-fg-muted">
                {(item.rate * (24 / item.interval_hours) * 365 * 100).toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
