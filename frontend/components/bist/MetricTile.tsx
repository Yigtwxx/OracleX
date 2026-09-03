import type { ReactNode } from 'react';

interface MetricTileProps {
  label: string;
  value: ReactNode;
  /** Secondary line: what the figure is measured against, or when. */
  note?: ReactNode;
  /** Tailwind colour class for the value. Defaults to neutral. */
  tone?: string;
  title?: string;
}

/**
 * One reading, labelled.
 *
 * Deliberately dumb: the caller has already decided what the number is and how
 * to colour it. A tile that formatted its own value would need to know whether
 * it was showing a rate, a ratio or a price, and that knowledge belongs with
 * the board that has the context.
 */
export default function MetricTile({ label, value, note, tone, title }: MetricTileProps) {
  return (
    <div className="surface-flat surface flex flex-col gap-1 p-3" title={title}>
      <span className="label">{label}</span>
      <span className={`tabnum text-lg font-semibold ${tone ?? 'text-fg'}`}>{value}</span>
      {note && <span className="text-2xs text-fg-subtle">{note}</span>}
    </div>
  );
}
