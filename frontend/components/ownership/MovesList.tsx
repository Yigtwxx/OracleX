'use client';

import type { OwnershipMove } from '@/lib/api';
import { assetIdentityClass } from '@/lib/assetIdentity';
import SourceBadge from './SourceBadge';
import { MOVE_BADGE, MOVE_LABEL, formatDate, formatQuantity, formatUsd } from './format';

interface MovesListProps {
  moves: OwnershipMove[];
  /** No prior observation exists yet, so an empty list is expected, not a gap. */
  baseline?: boolean;
  /** Prefixes each row with who moved. On for the cross-entity strip. */
  showEntity?: boolean;
  emptyMessage?: string;
}

export default function MovesList({
  moves,
  baseline = false,
  showEntity = false,
  emptyMessage,
}: MovesListProps) {
  if (moves.length === 0) {
    return (
      <p className="px-4 py-5 text-center text-xs text-fg-subtle">
        {baseline
          ? 'Baseline captured. Changes will appear from the next daily update.'
          : (emptyMessage ?? 'No moves recorded yet.')}
      </p>
    );
  }

  return (
    <ul>
      {moves.map((move) => {
        const symbol = move.asset_symbol ?? move.asset_label;
        // The gap between when it happened and when it surfaced is the honest
        // measure of this page's lag, so it is shown rather than smoothed over.
        const occurred = formatDate(move.occurred_at);
        const reported = formatDate(move.reported_at);
        const lagged = reported && occurred && reported !== occurred;

        return (
          <li
            key={move.id}
            className="flex items-start gap-3 border-b border-line px-4 py-2.5 last:border-b-0 hover:bg-surface-2"
          >
            <span className={`${MOVE_BADGE[move.kind]} shrink-0`}>{MOVE_LABEL[move.kind]}</span>

            <div className="min-w-0 flex-1">
              <p className="truncate text-xs text-fg">
                {showEntity && <span className="text-fg-muted">{move.entity_name} · </span>}
                <span className={assetIdentityClass(symbol)}>{move.asset_label}</span>
              </p>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-fg-subtle">
                {move.quantity_delta !== null && (
                  <span className="tabnum">
                    {move.quantity_delta > 0 ? '+' : ''}
                    {formatQuantity(move.quantity_delta, null)}
                  </span>
                )}
                {move.value_usd_delta !== null && (
                  <span className="tabnum">{formatUsd(Math.abs(move.value_usd_delta))}</span>
                )}
                <span>{occurred}</span>
                {lagged && <span title="Filed later than it happened">· filed {reported}</span>}
              </p>
            </div>

            <SourceBadge source={move.source} className="mt-0.5 shrink-0" />
          </li>
        );
      })}
    </ul>
  );
}
