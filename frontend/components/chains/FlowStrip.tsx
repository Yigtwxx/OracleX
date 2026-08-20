'use client';

import type { ChainsBoardResponse } from '@/lib/api';
import Panel from '@/components/ui/Panel';
import { NO_READING, formatCount, formatFlowUsd } from '@/lib/chain-format';

interface FlowStripProps {
  flows: ChainsBoardResponse['flows'];
}

/**
 * Yesterday's exchange flow, for the two chains the free feed covers.
 *
 * The only panel here that is not a live reading, and the design has to keep
 * saying so — everything around it updates every ten seconds, and a daily
 * figure sitting among them would otherwise be read as current. Hence the date
 * in the header rather than in a footnote, and "24h" on every label.
 *
 * The coverage limit is stated in the footnote rather than hidden. Six of the
 * eight chains on this board are absent because the feed refuses them, not
 * because nothing moved on them, and those are opposite claims.
 */
export default function FlowStrip({ flows }: FlowStripProps) {
  const hasData = flows.assets.some(
    (asset) => asset.net_flow_usd !== null || asset.active_addresses !== null
  );

  return (
    <Panel
      title="Exchange flow"
      action={
        <span className="text-2xs font-mono tabnum text-fg-subtle">
          {flows.as_of ?? NO_READING}
        </span>
      }
      footnote="Daily, not live. Published for Bitcoin and Ethereum only — the other six chains are not covered by this feed."
    >
      {!hasData ? (
        <div className="px-4 py-8 text-center">
          <p className="text-base text-fg-muted">Flow data is unavailable.</p>
          <p className="mt-1 text-xs text-fg-subtle">
            The metrics feed did not answer this refresh.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-line">
          {flows.assets.map((asset) => {
            const net = asset.net_flow_usd;
            return (
              <div key={asset.symbol} className="px-4 py-2.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-semibold text-fg">{asset.symbol}</span>
                  <span
                    className={`text-sm font-mono tabnum ${
                      net === null ? 'text-fg-subtle' : net > 0 ? 'text-down' : 'text-up'
                    }`}
                    // Onto an exchange is the direction that precedes selling,
                    // which is why an inflow is coloured as the bearish one.
                    // Spelled out because the sign alone does not say it.
                    title={
                      net === null
                        ? undefined
                        : net > 0
                          ? 'Net moved onto exchanges over 24h'
                          : 'Net moved off exchanges over 24h'
                    }
                  >
                    {formatFlowUsd(net)}
                  </span>
                </div>
                <div className="mt-0.5 flex items-baseline justify-between gap-2 text-2xs text-fg-subtle">
                  <span>{net === null ? '' : net > 0 ? 'onto exchanges' : 'off exchanges'}</span>
                  <span className="font-mono tabnum">
                    {formatCount(asset.active_addresses)} addrs · {formatCount(asset.transactions)}{' '}
                    txs
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
