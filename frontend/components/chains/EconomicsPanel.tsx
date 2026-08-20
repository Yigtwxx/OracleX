'use client';

import type { ChainRow } from '@/lib/api';
import Panel from '@/components/ui/Panel';
import { NO_READING, formatCount, formatCountdown, formatHashrate } from '@/lib/chain-format';

interface EconomicsPanelProps {
  chains: ChainRow[];
  now: number;
}

interface StatProps {
  label: string;
  value: string;
  detail?: string;
  tone?: 'default' | 'up' | 'down';
}

function Stat({ label, value, detail, tone = 'default' }: StatProps) {
  const toneClass = tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : 'text-fg';
  return (
    <div className="min-w-0">
      <div className="text-2xs text-fg-subtle truncate">{label}</div>
      <div className={`text-sm font-mono tabnum ${toneClass} truncate`}>{value}</div>
      {detail && <div className="text-2xs text-fg-subtle truncate">{detail}</div>}
    </div>
  );
}

/** A labelled progress bar, for the two countdowns that have a denominator. */
function Progress({ percent, label }: { percent: number | null | undefined; label: string }) {
  if (percent === null || percent === undefined) return null;
  return (
    <div className="col-span-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-2xs text-fg-subtle">{label}</span>
        <span className="text-2xs font-mono tabnum text-fg-muted">{percent.toFixed(1)}%</span>
      </div>
      <div className="mt-1 h-1 rounded-full bg-surface-2 overflow-hidden">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: `${Math.min(Math.max(percent, 0), 100)}%` }}
        />
      </div>
    </div>
  );
}

/**
 * The schedules each chain runs on, which no amount of watching blocks reveals.
 *
 * Only three of the eight have any: Bitcoin counts down to a halving and a
 * difficulty retarget, Ethereum burns a measurable amount of its own supply,
 * and Solana runs on epochs. The other five are left out rather than padded
 * with a row that says nothing — a panel of five "—" cells would imply those
 * chains have schedules that could not be read.
 *
 * Every countdown here is an estimate projected from the current rate, and the
 * copy says so. A halving date shown to the minute would be false precision:
 * it moves by days as hashrate changes.
 */
export default function EconomicsPanel({ chains, now }: EconomicsPanelProps) {
  const bitcoin = chains.find((chain) => chain.key === 'bitcoin');
  const ethereum = chains.find((chain) => chain.key === 'ethereum');
  const solana = chains.find((chain) => chain.key === 'solana');

  const btc = bitcoin?.economics;
  const sol = solana?.economics;

  return (
    <Panel
      title="Schedules"
      footnote="Countdowns are projected from the current rate and move as it changes."
    >
      <div className="divide-y divide-line">
        {btc && !bitcoin?.error && (
          <section className="px-4 py-3">
            <h4 className="text-2xs uppercase tracking-wide text-fg-subtle mb-2">Bitcoin</h4>
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <Stat
                label="Next halving"
                value={formatCountdown(btc.halving_estimated_at, now)}
                detail={
                  btc.halving_blocks_remaining
                    ? `${formatCount(btc.halving_blocks_remaining)} blocks · #${btc.halving_height?.toLocaleString('en-US')}`
                    : undefined
                }
              />
              <Stat
                label="Difficulty retarget"
                value={formatCountdown(btc.difficulty_retarget_at, now)}
                detail={
                  btc.difficulty_blocks_remaining
                    ? `${formatCount(btc.difficulty_blocks_remaining)} blocks`
                    : undefined
                }
              />
              <Stat
                label="Expected change"
                value={
                  btc.difficulty_change_percent === null ||
                  btc.difficulty_change_percent === undefined
                    ? NO_READING
                    : `${btc.difficulty_change_percent > 0 ? '+' : ''}${btc.difficulty_change_percent.toFixed(2)}%`
                }
                // Rising difficulty means the network got more secure, so up is
                // green — the same direction convention the rest of the app uses
                // for a number getting larger.
                tone={
                  btc.difficulty_change_percent === null ||
                  btc.difficulty_change_percent === undefined
                    ? 'default'
                    : btc.difficulty_change_percent >= 0
                      ? 'up'
                      : 'down'
                }
              />
              <Stat label="Hashrate" value={formatHashrate(btc.hashrate)} />
              <Progress percent={btc.difficulty_progress_percent} label="Retarget epoch progress" />
            </div>
          </section>
        )}

        {ethereum && !ethereum.error && (
          <section className="px-4 py-3">
            <h4 className="text-2xs uppercase tracking-wide text-fg-subtle mb-2">Ethereum</h4>
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <Stat
                label="Burned per day"
                value={
                  ethereum.burn_native_per_day === null ||
                  ethereum.burn_native_per_day === undefined
                    ? NO_READING
                    : `${ethereum.burn_native_per_day.toFixed(1)} ETH`
                }
                detail="base fee × gas used, at the current cadence"
              />
              <Stat
                label="Base fee"
                value={
                  ethereum.fee?.base_fee_gwei === null || ethereum.fee?.base_fee_gwei === undefined
                    ? NO_READING
                    : `${ethereum.fee.base_fee_gwei.toFixed(3)} gwei`
                }
              />
            </div>
          </section>
        )}

        {sol && !solana?.error && (
          <section className="px-4 py-3">
            <h4 className="text-2xs uppercase tracking-wide text-fg-subtle mb-2">Solana</h4>
            <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
              <Stat label="Epoch" value={sol.epoch?.toLocaleString('en-US') ?? NO_READING} />
              <Stat label="Epoch ends" value={formatCountdown(sol.epoch_ends_at, now)} />
              <Stat
                label="Throughput"
                value={
                  solana?.throughput?.non_vote_tps === null ||
                  solana?.throughput?.non_vote_tps === undefined
                    ? NO_READING
                    : `${formatCount(solana.throughput.non_vote_tps)} tps`
                }
                detail="excludes consensus votes"
              />
              <Stat
                label="Skipped slots"
                value={
                  solana?.throughput?.skipped_slot_percent === null ||
                  solana?.throughput?.skipped_slot_percent === undefined
                    ? NO_READING
                    : `${solana.throughput.skipped_slot_percent.toFixed(2)}%`
                }
              />
              <Progress percent={sol.epoch_progress_percent} label="Epoch progress" />
            </div>
          </section>
        )}
      </div>
    </Panel>
  );
}
