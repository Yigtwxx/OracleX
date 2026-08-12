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
    >
      <table className="w-full">
        <thead className="sticky top-0 z-10 bg-surface-2">
          <tr>
            <th className="label px-4 py-1.5 text-left">Symbol</th>
            <th className="label px-4 py-1.5 text-right">Rate</th>
            <th className="label px-4 py-1.5 text-right">Est. APR</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {/* Backend orders this: the fixed core block by market cap, then any
              outlier that cleared the extreme threshold, by funding intensity. */}
          {data.map((item) => {
            const isPositive = item.rate > 0;
            // Saturates just past the 0.05% extreme threshold, so an outlier
            // reads as a full bar while ordinary rates stay visibly short.
            const intensity = Math.min(Math.abs(item.rate) * 20000, 100);

            return (
              <tr key={item.symbol} className="hover:bg-surface-2 transition-colors">
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-base text-fg">{item.symbol}</span>
                    {item.is_extreme && (
                      <span
                        className={`text-2xs px-1.5 py-px rounded ${isPositive ? 'bg-up-bg text-up' : 'bg-down-bg text-down'}`}
                      >
                        EXTREME
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-2">
                  <div className="flex items-center justify-end gap-2">
                    {/* The rate is per settlement period, and those differ by pair. */}
                    <span className="text-2xs font-mono tabnum text-fg-subtle">
                      {item.interval_hours}h
                    </span>
                    <span
                      className={`text-base font-mono tabnum ${isPositive ? 'text-up' : 'text-down'}`}
                    >
                      {item.rate_formatted}
                    </span>
                    <div className="w-12 h-1 bg-line rounded-full overflow-hidden">
                      <div
                        className={`h-full ${isPositive ? 'bg-up' : 'bg-down'}`}
                        style={{
                          width: `${intensity}%`,
                          marginLeft: isPositive ? '0' : 'auto',
                        }}
                      />
                    </div>
                  </div>
                </td>
                {/* Not a quoted APR — the current rate held constant for a year. */}
                <td className="px-4 py-2 text-right text-base font-mono tabnum text-fg-muted">
                  {(item.rate * (24 / item.interval_hours) * 365 * 100).toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
