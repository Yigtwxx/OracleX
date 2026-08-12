'use client';

import Link from 'next/link';
import type { OwnershipMove } from '@/lib/api';
import { assetIdentityClass } from '@/lib/assetIdentity';
import { MOVE_BADGE, MOVE_LABEL, formatDate } from './format';

interface LatestMovesStripProps {
  moves: OwnershipMove[];
  /** True while every tracked holder is still at its first observation. */
  baseline?: boolean;
}

/**
 * The horizontal ticker above the grid.
 *
 * Scrolls sideways rather than wrapping: this is a glance surface, and a strip
 * that grows to three rows pushes the holders it is introducing off the screen.
 */
export default function LatestMovesStrip({ moves, baseline = false }: LatestMovesStripProps) {
  if (moves.length === 0) {
    return (
      <p className="text-2xs text-fg-subtle">
        {baseline
          ? 'Baseline captured. Changes will appear from the next daily update.'
          : 'No moves recorded in the tracked window.'}
      </p>
    );
  }

  return (
    <div>
      <p className="label mb-1.5">Latest moves</p>
      <div className="custom-scrollbar flex gap-2 overflow-x-auto pb-1">
        {moves.map((move) => (
          <Link
            key={move.id}
            href={`/ownership?entity=${encodeURIComponent(move.entity_id)}`}
            className="surface flex shrink-0 items-center gap-2 px-2.5 py-1.5 transition-colors hover:bg-surface-2"
            title={move.headline}
          >
            <span className={MOVE_BADGE[move.kind]}>{MOVE_LABEL[move.kind]}</span>
            <span className="whitespace-nowrap text-xs text-fg-muted">{move.entity_name}</span>
            <span
              className={`whitespace-nowrap text-xs font-medium ${assetIdentityClass(move.asset_symbol ?? move.asset_label)}`}
            >
              {move.asset_label}
            </span>
            <span className="whitespace-nowrap text-2xs text-fg-subtle">
              {formatDate(move.reported_at ?? move.occurred_at)}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
