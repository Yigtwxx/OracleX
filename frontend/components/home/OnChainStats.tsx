'use client';

import { OnChainData } from '@/lib/api';

interface OnChainStatsProps {
  data: OnChainData | null;
  isLoading: boolean;
}

interface StatCardProps {
  label: string;
  value: number | null;
  format: (value: number) => string;
  unit?: string;
  delta?: number | null;
  caption: (value: number) => string;
}

/** Shown wherever a metric could not be measured. Never a 0. */
const UNKNOWN = '—';
const UNKNOWN_CAPTION = 'Unavailable';

/**
 * Change indicator. A delta that rounds to zero is not a direction, so it stays
 * neutral instead of rendering as a green rise. An unmeasured delta shows nothing.
 */
function Delta({ value }: { value: number | null }) {
  if (value === null) return null;

  const rounded = Math.abs(value) < 0.005 ? 0 : value;
  if (rounded === 0) {
    return <span className="text-sm font-mono tabnum text-fg-subtle">0.00%</span>;
  }
  return (
    <span className={`text-sm font-mono tabnum ${rounded > 0 ? 'text-up' : 'text-down'}`}>
      {rounded > 0 ? '▲' : '▼'} {Math.abs(rounded).toFixed(2)}%
    </span>
  );
}

/**
 * Single stat cell. Neutral surface — colour appears only on the delta.
 *
 * `format` and `caption` only ever see a real reading: when the value is null the
 * card renders the unknown state instead, so an outage cannot surface as a
 * confident "0.0 Gwei / Low cost".
 */
function StatCard({ label, value, format, unit, delta, caption }: StatCardProps) {
  const isKnown = value !== null;

  return (
    <div className="surface p-4">
      <div className="label">{label}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={`text-xl font-mono tabnum ${isKnown ? 'text-fg' : 'text-fg-subtle'}`}>
          {isKnown ? format(value) : UNKNOWN}
        </span>
        {isKnown && unit && <span className="text-sm text-fg-subtle">{unit}</span>}
        {isKnown && delta !== undefined && <Delta value={delta} />}
      </div>
      <div className="mt-1 text-sm text-fg-subtle">
        {isKnown ? caption(value) : UNKNOWN_CAPTION}
      </div>
    </div>
  );
}

/** Exchange flow cell. Direction is the meaning here, so it carries the colour. */
function FlowCard({
  label,
  valueUsd,
  asOf,
}: {
  label: string;
  valueUsd: number | null;
  asOf: string | null;
}) {
  if (valueUsd === null) {
    return (
      <div className="surface p-4">
        <div className="label">{label}</div>
        <div className="mt-2">
          <span className="text-xl font-mono tabnum text-fg-subtle">{UNKNOWN}</span>
        </div>
        <div className="mt-1 text-sm text-fg-subtle">{UNKNOWN_CAPTION}</div>
      </div>
    );
  }

  const isOutflow = valueUsd < 0;
  const millions = Math.abs(valueUsd) / 1_000_000;

  return (
    <div className="surface p-4">
      <div className="label">{label}</div>
      <div className="mt-2">
        <span className={`text-xl font-mono tabnum ${isOutflow ? 'text-up' : 'text-down'}`}>
          {isOutflow ? '−' : '+'}${millions.toFixed(1)}M
        </span>
      </div>
      <div className="mt-1 text-sm text-fg-subtle">
        {isOutflow ? 'Net outflow (bullish)' : 'Net inflow (bearish)'}
        {asOf && <span className="text-fg-subtle"> · {asOf}</span>}
      </div>
    </div>
  );
}

function formatCount(value: number): string {
  return value.toLocaleString('en-US');
}

function formatGwei(gwei: number): string {
  if (gwei > 0 && gwei < 1) return gwei.toFixed(2);
  if (gwei < 10) return gwei.toFixed(1);
  return Math.round(gwei).toLocaleString('en-US');
}

function gasCaption(gwei: number): string {
  if (gwei < 5) return 'Low cost';
  if (gwei < 30) return 'Moderate';
  return 'High cost';
}

function formatMempool(vbytes: number): string {
  return (vbytes / 1_000_000).toFixed(1);
}

function mempoolCaption(vbytes: number): string {
  const megabytes = vbytes / 1_000_000;
  if (megabytes < 5) return 'Clear';
  if (megabytes < 50) return 'Normal';
  return 'Congested';
}

const DAILY_ACTIVE = () => 'Daily active users';
const LAST_CLOSE = () => 'Last full UTC day';

export default function OnChainStats({ data, isLoading }: OnChainStatsProps) {
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="surface h-[104px] shimmer" />
        ))}
      </div>
    );
  }

  const { active_addresses, transactions_24h, network_load, exchange_flows } = data;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
      <StatCard
        label="BTC Active Addresses"
        value={active_addresses.btc}
        format={formatCount}
        delta={active_addresses.btc_change_24h}
        caption={DAILY_ACTIVE}
      />
      <StatCard
        label="ETH Active Addresses"
        value={active_addresses.eth}
        format={formatCount}
        delta={active_addresses.eth_change_24h}
        caption={DAILY_ACTIVE}
      />
      <StatCard
        label="Network Gas (ETH)"
        value={network_load.eth_gas_gwei}
        format={formatGwei}
        unit="Gwei"
        caption={gasCaption}
      />
      <FlowCard
        label="BTC Exchange Netflow"
        valueUsd={exchange_flows.btc_net_flow_usd}
        asOf={exchange_flows.as_of}
      />
      <StatCard
        label="BTC Transactions"
        value={transactions_24h.btc}
        format={formatCount}
        caption={LAST_CLOSE}
      />
      <StatCard
        label="ETH Transactions"
        value={transactions_24h.eth}
        format={formatCount}
        caption={LAST_CLOSE}
      />
      <StatCard
        label="BTC Mempool"
        value={network_load.btc_mempool_size_vbytes}
        format={formatMempool}
        unit="MB"
        caption={mempoolCaption}
      />
      <FlowCard
        label="ETH Exchange Netflow"
        valueUsd={exchange_flows.eth_net_flow_usd}
        asOf={exchange_flows.as_of}
      />
    </div>
  );
}
