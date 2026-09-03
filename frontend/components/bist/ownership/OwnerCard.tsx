'use client';

import { AlertTriangle } from 'lucide-react';

import type { BistOwnershipEntity } from '@/lib/bist-api';
import { formatCompactTry, formatPercent } from '@/lib/bist-format';
import { CATEGORY_LABEL } from '@/lib/bist-ownership';
import OwnerAllocationBar from './OwnerAllocationBar';

interface OwnerCardProps {
  entity: BistOwnershipEntity;
  onOpen: (entityId: string) => void;
}

/**
 * One holder on the grid.
 *
 * The total is the sum of what could be valued, and the card says so under
 * the bar rather than printing a number that looks like net worth. An entity
 * with no position is still a card — greyed and explained — because a board
 * that silently dropped it would read as "we never track them".
 */
export default function OwnerCard({ entity, onOpen }: OwnerCardProps) {
  const empty = !entity.has_data;

  return (
    <button
      type="button"
      onClick={() => onOpen(entity.id)}
      className={`surface surface-flat flex w-full flex-col gap-3 p-3 text-left transition-colors hover:bg-surface-2 ${
        empty ? 'opacity-70' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-base font-semibold text-fg">{entity.name}</p>
          <p className="truncate text-2xs text-fg-subtle">
            {CATEGORY_LABEL[entity.category]}
            {entity.subtitle ? ` · ${entity.subtitle}` : ''}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="tabnum text-base font-semibold text-fg">
            {entity.total_value_try === null ? '—' : formatCompactTry(entity.total_value_try)}
          </p>
          <p className="text-2xs text-fg-subtle">
            {entity.positions_count} pozisyon
            {entity.stale && (
              <span className="ml-1 text-warn" title="Pano bir günden eski">
                ·eski
              </span>
            )}
          </p>
        </div>
      </div>

      <OwnerAllocationBar slices={entity.allocation} />

      {empty ? (
        <p className="text-2xs text-fg-subtle">
          {entity.issues[0] ?? 'XU100 kartlarında bu ortağın %5 üzeri payı yok.'}
        </p>
      ) : (
        <ul className="space-y-1">
          {entity.top_positions.map((position) => (
            <li key={position.ticker} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate text-fg">
                <span className="font-medium">{position.ticker}</span>
                <span className="ml-1.5 text-fg-muted">{position.name}</span>
              </span>
              <span className="tabnum shrink-0 text-fg-muted">
                {formatPercent(position.stake_pct)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {!empty && entity.issues.length > 0 && (
        <p className="flex items-start gap-1 text-2xs text-warn">
          <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
          <span>{entity.issues[0]}</span>
        </p>
      )}

      {entity.last_move && (
        <p className="truncate text-2xs text-fg-subtle" title={entity.last_move.headline}>
          Son bildirim · {entity.last_move.headline}
        </p>
      )}
    </button>
  );
}
