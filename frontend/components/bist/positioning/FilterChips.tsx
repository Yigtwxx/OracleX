'use client';

import { X } from 'lucide-react';

import { formatPercent } from '@/lib/bist-format';
import {
  QUADRANT_LABEL,
  RANGE_BUCKETS,
  isFilterActive,
  type PositioningFilter,
} from '@/lib/bist-positioning';

interface FilterChipsProps {
  filter: PositioningFilter;
  /** How many names survive the filter, so the strip states its own cost. */
  matched: number;
  total: number;
  onChange: (filter: PositioningFilter) => void;
}

/**
 * What is currently narrowing the board, and how to stop it.
 *
 * Four panels can each contribute a clause and three of them are charts, so
 * without this the reader can arrive at a board showing eleven rows with the
 * reason sitting in a highlighted tile they have already scrolled past. The
 * strip is the one place that always says the whole filter in words.
 */
export default function FilterChips({ filter, matched, total, onChange }: FilterChipsProps) {
  if (!isFilterActive(filter)) return null;

  const chips: { key: string; label: string; clear: PositioningFilter }[] = [];

  if (filter.sector !== undefined) {
    chips.push({
      key: 'sector',
      label: filter.sector,
      clear: { ...filter, sector: undefined },
    });
  }
  if (filter.quadrant !== undefined) {
    chips.push({
      key: 'quadrant',
      label: QUADRANT_LABEL[filter.quadrant],
      clear: { ...filter, quadrant: undefined },
    });
  }
  if (filter.rangeBucket !== undefined) {
    const from = filter.rangeBucket / RANGE_BUCKETS;
    const to = (filter.rangeBucket + 1) / RANGE_BUCKETS;
    chips.push({
      key: 'range',
      label: `Yıllık konum ${formatPercent(from, 0)}–${formatPercent(to, 0)}`,
      clear: { ...filter, rangeBucket: undefined },
    });
  }

  return (
    <div className="surface surface-flat flex flex-wrap items-center gap-2 px-3 py-2">
      <span className="label">Filtre</span>
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={() => onChange(chip.clear)}
          className="inline-flex items-center gap-1 rounded-md border border-line-strong bg-surface-2 px-2 py-0.5 text-2xs text-fg transition-colors hover:border-fg-subtle"
        >
          {chip.label}
          <X className="h-3 w-3 text-fg-subtle" aria-hidden="true" />
          <span className="sr-only">filtresini kaldır</span>
        </button>
      ))}
      <span className="tabnum ml-auto text-2xs text-fg-muted">
        {matched} / {total} hisse
      </span>
      <button
        type="button"
        onClick={() => onChange({})}
        className="text-2xs text-fg-subtle underline-offset-2 transition-colors hover:text-fg hover:underline"
      >
        Tümünü temizle
      </button>
    </div>
  );
}
