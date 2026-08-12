'use client';

import type { LucideIcon } from 'lucide-react';

/**
 * One number and what it means.
 *
 * The number carries the emphasis and the label stays quiet — four cards of
 * equally loud text read as a wall rather than a summary.
 */
export default function StatCard({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: number | string;
  icon?: LucideIcon;
  hint?: string;
}) {
  return (
    <div className="surface p-4">
      <div className="flex items-center gap-1.5 text-sm text-fg-subtle">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        {label}
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-fg">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {hint && <p className="mt-0.5 text-sm text-fg-subtle">{hint}</p>}
    </div>
  );
}
