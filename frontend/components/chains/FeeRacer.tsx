'use client';

import { useMemo, useState } from 'react';
import type { ChainRow } from '@/lib/api';
import Panel from '@/components/ui/Panel';
import { CHAIN_TINT, NO_READING, formatUsd } from '@/lib/chain-format';

interface FeeRacerProps {
  chains: ChainRow[];
}

/** Amounts a reader is likely to be thinking about, as one-tap presets. */
const PRESETS = [100, 1_000, 10_000, 100_000];

/**
 * What it costs to move value on each chain right now, cheapest first.
 *
 * The one panel on this board that answers a question rather than reporting a
 * measurement, and it needs no data of its own — every figure here was already
 * fetched to fill the cards above.
 *
 * The amount field is the honest part of the design. On every chain here a
 * simple transfer costs the same whether it moves ten dollars or ten million:
 * fees price computation and bytes, not value. So the amount does not change
 * any fee — it changes the *percentage*, which is the number that actually
 * decides whether a chain is usable for a given size of payment. Sending $100
 * over Ethereum at three tenths of a cent is nothing; the same fee on a $2
 * payment is not. Showing the cost alone would hide that, and scaling the fee
 * by the amount would be a fabrication.
 */
export default function FeeRacer({ chains }: FeeRacerProps) {
  const [amount, setAmount] = useState(1_000);

  const rows = useMemo(() => {
    return (
      chains
        .filter((chain) => !chain.error && chain.fee)
        .map((chain) => ({
          chain,
          usd: chain.fee?.transfer_usd ?? null,
          isFree: chain.fee?.transfer_native === 0,
        }))
        // Unpriced rows sink to the bottom rather than sorting as free, which is
        // where a null would land in a plain numeric comparison.
        .sort((a, b) => {
          if (a.usd === null && b.usd === null) return 0;
          if (a.usd === null) return 1;
          if (b.usd === null) return -1;
          return a.usd - b.usd;
        })
    );
  }, [chains]);

  const cheapest = rows.find((row) => row.usd !== null && row.usd > 0)?.usd ?? null;

  return (
    <Panel
      title="Cost to send"
      action={
        <div className="flex items-center gap-1">
          {PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => setAmount(preset)}
              aria-pressed={amount === preset}
              className={`px-1.5 py-0.5 rounded text-2xs font-mono tabnum transition-colors ${
                amount === preset
                  ? 'bg-surface-2 text-fg'
                  : 'text-fg-subtle hover:text-fg hover:bg-surface-2'
              }`}
            >
              ${preset >= 1000 ? `${preset / 1000}k` : preset}
            </button>
          ))}
        </div>
      }
      footnote="One simple value transfer, priced at each chain's live rate. Rollup rows include the L1 data fee."
    >
      <div className="divide-y divide-line">
        {rows.map(({ chain, usd, isFree }) => {
          const tint = CHAIN_TINT[chain.key] ?? 'var(--accent)';
          // Relative to the cheapest priced chain, on a log scale — the spread
          // runs five orders of magnitude, and a linear bar would render seven
          // of the eight rows as an invisible sliver next to Bitcoin.
          const ratio = usd !== null && usd > 0 && cheapest ? Math.log10(usd / cheapest) / 5 : null;
          const share = usd !== null && amount > 0 ? (usd / amount) * 100 : null;

          return (
            <div key={chain.key} className="px-4 py-2 flex items-center gap-3">
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: tint }}
                aria-hidden
              />
              <span className="text-sm text-fg w-28 shrink-0 truncate">{chain.name}</span>

              <div className="flex-1 min-w-0 h-1 rounded-full bg-surface-2 overflow-hidden">
                {ratio !== null && (
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.max(3, Math.min(ratio * 100, 100))}%`,
                      background: tint,
                    }}
                  />
                )}
              </div>

              <span className="text-sm font-mono tabnum text-fg w-20 text-right shrink-0">
                {isFree ? 'free' : formatUsd(usd)}
              </span>
              <span
                className="text-2xs font-mono tabnum text-fg-subtle w-16 text-right shrink-0"
                title={
                  isFree
                    ? (chain.fee?.free_reason ?? undefined)
                    : `Share of a $${amount.toLocaleString('en-US')} transfer`
                }
              >
                {isFree
                  ? '0%'
                  : share === null
                    ? NO_READING
                    : share < 0.001
                      ? '<0.001%'
                      : `${share.toFixed(3)}%`}
              </span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
