'use client';

import type { BistOwnershipEntity } from '@/lib/bist-api';
import { formatCompactTry } from '@/lib/bist-format';

interface OwnerRailProps {
  entities: BistOwnershipEntity[];
  activeId: string;
  onSelect: (entityId: string) => void;
}

/** The holder list beside a detail view, so moving between them is one click. */
export default function OwnerRail({ entities, activeId, onSelect }: OwnerRailProps) {
  return (
    <nav aria-label="Ortaklar" className="surface surface-flat overflow-hidden">
      <ul className="custom-scrollbar max-h-[calc(100vh-14rem)] overflow-y-auto">
        {entities.map((entity) => {
          const active = entity.id === activeId;
          return (
            <li key={entity.id} className="border-b border-line last:border-0">
              <button
                type="button"
                onClick={() => onSelect(entity.id)}
                aria-current={active ? 'true' : undefined}
                className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-surface-2 ${
                  active ? 'bg-surface-2 text-fg' : 'text-fg-muted'
                }`}
              >
                <span className="min-w-0 truncate">{entity.name}</span>
                <span className="tabnum shrink-0 text-2xs text-fg-subtle">
                  {entity.total_value_try === null ? '—' : formatCompactTry(entity.total_value_try)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
