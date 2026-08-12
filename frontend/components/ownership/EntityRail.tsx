'use client';

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import type { OwnershipEntity } from '@/lib/api';
import EntityAvatar from './EntityAvatar';
import { formatUsd } from './format';

interface EntityRailProps {
  entities: OwnershipEntity[];
  activeId: string;
  onSelect: (entityId: string) => void;
}

/**
 * The narrow list beside the detail pane.
 *
 * Selection goes through `onSelect` rather than a Link so the pane swaps
 * without a scroll reset — the reader is comparing two holders, and dropping
 * them at the top of the page on every switch makes that impossible.
 */
export default function EntityRail({ entities, activeId, onSelect }: EntityRailProps) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entities;
    return entities.filter(
      (entity) =>
        entity.name.toLowerCase().includes(needle) ||
        (entity.subtitle ?? '').toLowerCase().includes(needle)
    );
  }, [entities, query]);

  return (
    <div className="surface flex h-full min-h-0 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search holders"
          aria-label="Search holders"
          className="w-full bg-transparent text-xs text-fg placeholder:text-fg-subtle focus:outline-none"
        />
      </div>

      <ul className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
        {filtered.map((entity) => {
          const isActive = entity.id === activeId;
          return (
            <li key={entity.id}>
              <button
                type="button"
                onClick={() => onSelect(entity.id)}
                aria-current={isActive ? 'true' : undefined}
                className={[
                  'flex w-full items-center gap-2 border-l-2 px-3 py-2 text-left transition-colors',
                  isActive
                    ? 'border-accent bg-surface-2 text-fg'
                    : 'border-transparent text-fg-muted hover:bg-surface-2 hover:text-fg',
                ].join(' ')}
              >
                <EntityAvatar entity={entity} size="sm" />
                <span className="min-w-0 flex-1 truncate text-xs font-medium">{entity.name}</span>
                <span className="tabnum shrink-0 text-2xs text-fg-subtle">
                  {formatUsd(entity.total_value_usd)}
                </span>
              </button>
            </li>
          );
        })}

        {filtered.length === 0 && (
          <li className="px-3 py-3 text-2xs text-fg-subtle">No holder matches “{query}”.</li>
        )}
      </ul>
    </div>
  );
}
