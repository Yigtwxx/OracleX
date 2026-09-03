'use client';

import type { BistHolderCategory } from '@/lib/bist-api';
import { CATEGORY_LABEL, CATEGORY_ORDER } from '@/lib/bist-ownership';

interface OwnerCategoryChipsProps {
  counts: Record<string, number>;
  active: BistHolderCategory | null;
  onChange: (category: BistHolderCategory | null) => void;
}

/** One chip per holder category, with how many cards each would show. */
export default function OwnerCategoryChips({ counts, active, onChange }: OwnerCategoryChipsProps) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const chips: { key: BistHolderCategory | null; label: string; count: number }[] = [
    { key: null, label: 'Tümü', count: total },
    ...CATEGORY_ORDER.filter((c) => (counts[c] ?? 0) > 0).map((c) => ({
      key: c,
      label: CATEGORY_LABEL[c],
      count: counts[c] ?? 0,
    })),
  ];

  return (
    <div role="group" aria-label="Ortak türü" className="flex flex-wrap gap-1.5">
      {chips.map((chip) => {
        const selected = chip.key === active;
        return (
          <button
            key={chip.key ?? 'all'}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(chip.key)}
            className={`rounded-md border px-2.5 py-1 text-sm transition-colors ${
              selected
                ? 'border-line-strong bg-surface-2 text-fg'
                : 'border-line text-fg-muted hover:border-line-strong hover:text-fg'
            }`}
          >
            {chip.label}
            <span className="tabnum ml-1.5 text-2xs text-fg-subtle">{chip.count}</span>
          </button>
        );
      })}
    </div>
  );
}
