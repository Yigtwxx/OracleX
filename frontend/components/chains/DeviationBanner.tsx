'use client';

import { AlertTriangle } from 'lucide-react';
import type { ChainRow } from '@/lib/api';
import { CADENCE_ALERT_THRESHOLD, cadenceDeviation, formatDuration } from '@/lib/chain-format';

interface DeviationBannerProps {
  chains: ChainRow[];
}

/**
 * Chains running visibly off their own cadence, and chains that could not be
 * read at all.
 *
 * Renders nothing when everything is normal, which is the point: this is the
 * only element on the board that appears rather than updates, so its presence
 * is itself the signal. A permanent "all systems normal" strip would be one
 * more thing to scan past and would train the reader to stop seeing it.
 *
 * Only lateness is reported, not earliness. A chain running fast is not a
 * problem anyone needs told about, and half the entries on a two-sided banner
 * would be noise.
 */
export default function DeviationBanner({ chains }: DeviationBannerProps) {
  const unreachable = chains.filter((chain) => chain.error);
  const slow = chains.filter((chain) => {
    if (chain.error) return false;
    const deviation = cadenceDeviation(chain);
    return deviation !== null && deviation > CADENCE_ALERT_THRESHOLD;
  });

  if (unreachable.length === 0 && slow.length === 0) return null;

  return (
    <div className="surface px-4 py-2 flex items-start gap-2.5">
      <AlertTriangle className="w-3.5 h-3.5 text-warn shrink-0 mt-0.5" aria-hidden />
      <div className="min-w-0 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {slow.map((chain) => {
          const deviation = cadenceDeviation(chain);
          return (
            <span key={chain.key} className="text-xs text-fg-muted">
              <span className="text-fg">{chain.name}</span> at{' '}
              <span className="font-mono tabnum">{formatDuration(chain.block_time_seconds)}</span>,{' '}
              {((deviation ?? 0) * 100).toFixed(0)}% above its{' '}
              <span className="font-mono tabnum">{formatDuration(chain.target_block_seconds)}</span>{' '}
              target
            </span>
          );
        })}
        {unreachable.map((chain) => (
          <span key={chain.key} className="text-xs text-fg-muted">
            <span className="text-fg">{chain.name}</span> could not be reached — the row is blank,
            not idle
          </span>
        ))}
      </div>
    </div>
  );
}
