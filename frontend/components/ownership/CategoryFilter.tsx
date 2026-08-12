'use client';

import type { OwnershipCategory } from '@/lib/api';
import { CATEGORY_LABEL, CATEGORY_ORDER } from './format';

interface CategoryFilterProps {
  counts: Record<string, number>;
  active: OwnershipCategory | null;
  onChange: (category: OwnershipCategory | null) => void;
}

/**
 * Category chips above the grid.
 *
 * A category with nothing in it is not rendered. The alternative — a chip that
 * filters to an empty grid — teaches the reader that the page is broken when
 * what actually happened is that a later phase has not shipped its source yet.
 */
export default function CategoryFilter({ counts, active, onChange }: CategoryFilterProps) {
  const available = CATEGORY_ORDER.filter((category) => (counts[category] ?? 0) > 0);
  const total = available.reduce((sum, category) => sum + (counts[category] ?? 0), 0);

  // One category is not a choice.
  if (available.length < 2) return null;

  const chipClass = (isActive: boolean) =>
    [
      'rounded border px-2 py-1 text-2xs uppercase tracking-wide transition-colors',
      isActive
        ? 'border-accent text-fg'
        : 'border-line text-fg-subtle hover:border-line-strong hover:text-fg-muted',
    ].join(' ');

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button type="button" onClick={() => onChange(null)} className={chipClass(active === null)}>
        All <span className="tabnum">{total}</span>
      </button>
      {available.map((category) => (
        <button
          key={category}
          type="button"
          onClick={() => onChange(category)}
          className={chipClass(active === category)}
        >
          {CATEGORY_LABEL[category]} <span className="tabnum">{counts[category]}</span>
        </button>
      ))}
    </div>
  );
}
