'use client';

import Link from 'next/link';
import { AlertTriangle } from 'lucide-react';
import type { OwnershipEntity } from '@/lib/api';
import { assetIdentityClass } from '@/lib/assetIdentity';
import AllocationBar from './AllocationBar';
import EntityAvatar from './EntityAvatar';
import SourceBadge from './SourceBadge';
import {
  MOVE_BADGE,
  MOVE_LABEL,
  UNKNOWN,
  allocationColorsByKey,
  formatQuantity,
  formatUsd,
} from './format';

interface EntityCardProps {
  entity: OwnershipEntity;
}

/**
 * One holder on the grid.
 *
 * A card is never dropped for having no data. An entity that disappears during
 * a source outage reads as "sold everything" — a claim the outage does not
 * entitle us to make — so it stays, with a stale marker and an unknown total.
 *
 * The card is a link rather than a click handler so it opens in a new tab,
 * gets a real focus ring, and shows its destination on hover. The detail view
 * lives at a URL for the same reason: it has to be shareable.
 */
export default function EntityCard({ entity }: EntityCardProps) {
  const isUnknown = entity.total_value_usd === null;
  const sliceColors = allocationColorsByKey(entity.allocation);

  return (
    <Link
      href={`/ownership?entity=${encodeURIComponent(entity.id)}`}
      className="surface group flex flex-col gap-3 p-4 transition-colors hover:bg-surface-2 focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
    >
      <div className="flex items-start gap-2.5">
        <EntityAvatar entity={entity} size="md" />

        <div className="min-w-0 flex-1">
          <h3 className="truncate text-md font-semibold text-fg group-hover:text-accent">
            {entity.name}
          </h3>
          {entity.subtitle && <p className="truncate text-2xs text-fg-subtle">{entity.subtitle}</p>}
        </div>

        {entity.stale && (
          <span
            className="flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-2xs uppercase text-fg-subtle"
            title={entity.issues.join(' · ') || 'Figures replayed from an earlier refresh'}
          >
            <AlertTriangle className="h-2.5 w-2.5" aria-hidden />
            Stale
          </span>
        )}
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <span
          className={`tabnum text-lg font-semibold ${isUnknown ? 'text-fg-subtle' : 'text-fg'}`}
        >
          {formatUsd(entity.total_value_usd)}
        </span>
        <span className="text-2xs text-fg-subtle">
          {entity.positions_count === 1 ? '1 holding' : `${entity.positions_count} holdings`}
        </span>
      </div>

      <AllocationBar slices={entity.allocation} />

      {entity.top_positions.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {entity.top_positions.map((position) => (
            <li key={position.key} className="flex items-baseline justify-between gap-3 text-xs">
              <span
                className={`truncate font-medium ${
                  // The colour is the only thing linking this row to its segment
                  // in the bar above, so it comes from the same resolution pass.
                  // A holding too small to be named up there keeps the ordinary
                  // foreground rather than borrowing a colour it does not own.
                  sliceColors[position.key]?.text ??
                  assetIdentityClass(position.symbol ?? position.label)
                }`}
                style={{ color: sliceColors[position.key]?.hex }}
              >
                {position.label}
              </span>
              <span className="tabnum shrink-0 text-fg-muted">
                {formatQuantity(position.quantity, position.quantity_unit)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        /* Two different states that must not read the same. A source that
           failed is an outage; a Form 4 holder with nothing to report is a
           quiet quarter, and calling that "could not be sourced" would blame
           us for a fact about them. */
        <p className="text-xs text-fg-subtle">
          {entity.stale
            ? `${UNKNOWN} — no holdings could be sourced`
            : 'Reports trades, not holdings'}
        </p>
      )}

      {entity.last_move && (
        <p className="flex items-center gap-1.5 truncate border-t border-line pt-2 text-2xs">
          <span className={MOVE_BADGE[entity.last_move.kind]}>
            {MOVE_LABEL[entity.last_move.kind]}
          </span>
          <span className="truncate text-fg-muted">{entity.last_move.asset_label}</span>
        </p>
      )}

      {entity.top_positions[0] && (
        <div className="mt-auto flex items-center pt-1">
          <SourceBadge source={entity.top_positions[0].source} showDate asText />
        </div>
      )}
    </Link>
  );
}
