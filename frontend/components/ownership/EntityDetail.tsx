'use client';

import { AlertTriangle } from 'lucide-react';
import type { OwnershipEntity } from '@/lib/api';
import { useOwnershipEntity } from '@/hooks/queries';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';
import AllocationBar from './AllocationBar';
import EntityAvatar from './EntityAvatar';
import MovesList from './MovesList';
import PositionTable from './PositionTable';
import { UNKNOWN, formatDate, formatUsd } from './format';

interface EntityDetailProps {
  entityId: string;
  /** From the board, so the header renders before the detail request lands. */
  fallback?: OwnershipEntity;
  onSelectAsset?: (symbol: string) => void;
}

/**
 * One holder, fully expanded.
 *
 * The header is drawn from the board's summary while the position list is
 * still loading, so switching holders never blanks the pane — only the table
 * shimmers.
 */
export default function EntityDetail({ entityId, fallback, onSelectAsset }: EntityDetailProps) {
  const detail = useOwnershipEntity(entityId);
  const entity = detail.data?.entity ?? fallback;

  if (!entity) {
    return <PanelSkeleton />;
  }

  const asOf = formatDate(entity.as_of);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <header className="surface shrink-0 p-4">
        <div className="flex items-start gap-3">
          <EntityAvatar entity={entity} size="lg" />

          <div className="min-w-0 flex-1">
            <h2 className="truncate text-md font-semibold text-fg">{entity.name}</h2>
            <p className="truncate text-2xs text-fg-subtle">
              {entity.subtitle}
              {entity.source_label && <> · {entity.source_label}</>}
              {asOf && <> · as of {asOf}</>}
            </p>
          </div>

          <div className="shrink-0 text-right">
            <p
              className={`tabnum text-lg font-semibold ${entity.total_value_usd === null ? 'text-fg-subtle' : 'text-fg'}`}
            >
              {formatUsd(entity.total_value_usd)}
            </p>
            <p className="text-2xs text-fg-subtle">
              {entity.positions_count === 1 ? '1 holding' : `${entity.positions_count} holdings`}
            </p>
          </div>
        </div>

        <AllocationBar slices={entity.allocation} showLegend className="mt-3" />

        {/* The bar always fills to 100% of what we know, which is not the same
            as 100% of what they own. Saying so is not optional. */}
        {entity.coverage_note && (
          <p className="mt-2 text-2xs text-fg-subtle">{entity.coverage_note}</p>
        )}

        {entity.issues.length > 0 && (
          <ul className="mt-2 flex flex-col gap-0.5">
            {entity.issues.map((issue) => (
              <li key={issue} className="flex items-start gap-1.5 text-2xs text-warn">
                <AlertTriangle className="mt-0.5 h-2.5 w-2.5 shrink-0" aria-hidden />
                {issue}
              </li>
            ))}
          </ul>
        )}
      </header>

      <div className="custom-scrollbar flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overflow-x-hidden">
        <Panel
          title="Holdings"
          footnote={
            detail.data?.positions.some((p) => p.value_basis === 'marked')
              ? 'Values marked ~ are a reported quantity priced at a rate we fetched, not a figure the source published.'
              : undefined
          }
          className="shrink-0"
        >
          {detail.isLoading ? (
            <div className="shimmer h-40" />
          ) : detail.isError ? (
            <p className="px-4 py-6 text-center text-xs text-fg-muted">
              Could not load this holder&apos;s positions.
            </p>
          ) : (
            <PositionTable
              positions={detail.data?.positions ?? []}
              baseline={detail.data?.moves_baseline ?? false}
              dominantSourceLabel={entity.source_label}
              onSelectAsset={onSelectAsset}
            />
          )}
        </Panel>

        <Panel title="Moves" className="shrink-0">
          {detail.isLoading ? (
            <div className="shimmer h-24" />
          ) : (
            <MovesList
              moves={detail.data?.moves ?? []}
              baseline={detail.data?.moves_baseline ?? false}
            />
          )}
        </Panel>

        {detail.data && detail.data.sources.length > 0 && (
          <p className="shrink-0 px-1 pb-1 text-2xs text-fg-subtle">
            Sources: {detail.data.sources.map((source) => source.label).join(' · ') || UNKNOWN}
          </p>
        )}
      </div>
    </div>
  );
}
