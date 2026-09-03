'use client';

import { X } from 'lucide-react';

import { QUADRANT_LABEL, type Quadrant } from '@/lib/bist-positioning';

interface ViopFilterChipsProps {
  underlying?: string;
  quadrant?: Quadrant;
  /** How many contracts survive the filter, so the strip states its own cost. */
  matched: number;
  total: number;
  onClearUnderlying: () => void;
  onClearQuadrant: () => void;
  onClearAll: () => void;
}

/**
 * What is currently narrowing the board, and how to stop it.
 *
 * Two panels can each contribute a clause and both are charts, so without this
 * the reader can arrive at a table showing four rows with the reason sitting in
 * a highlighted bar they have already scrolled past. The strip is the one place
 * that always says the whole filter in words.
 */
export default function ViopFilterChips({
  underlying,
  quadrant,
  matched,
  total,
  onClearUnderlying,
  onClearQuadrant,
  onClearAll,
}: ViopFilterChipsProps) {
  if (underlying === undefined && quadrant === undefined) return null;

  const chips: { key: string; label: string; clear: () => void }[] = [];
  if (underlying !== undefined) {
    chips.push({ key: 'underlying', label: underlying, clear: onClearUnderlying });
  }
  if (quadrant !== undefined) {
    chips.push({ key: 'quadrant', label: QUADRANT_LABEL[quadrant], clear: onClearQuadrant });
  }

  return (
    <div className="surface surface-flat flex flex-wrap items-center gap-2 px-3 py-2">
      <span className="label">Filtre</span>
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={chip.clear}
          className="inline-flex items-center gap-1 rounded-md border border-line-strong bg-surface-2 px-2 py-0.5 text-2xs text-fg transition-colors hover:border-fg-subtle"
        >
          {chip.label}
          <X className="h-3 w-3 text-fg-subtle" aria-hidden="true" />
          <span className="sr-only">filtresini kaldır</span>
        </button>
      ))}
      <span className="tabnum ml-auto text-2xs text-fg-muted">
        {matched} / {total} sözleşme
      </span>
      <button
        type="button"
        onClick={onClearAll}
        className="text-2xs text-fg-subtle underline-offset-2 transition-colors hover:text-fg hover:underline"
      >
        Tümünü temizle
      </button>
    </div>
  );
}
