import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

interface StatusMessageProps {
  icon: LucideIcon;
  children: ReactNode;
  /** Usually a retry button. Omitted when there is nothing the reader can do. */
  action?: ReactNode;
}

/**
 * The centred "there is nothing here, and here is why" surface.
 *
 * One component for loading, empty and failed, distinguished by the icon and
 * the sentence rather than by three different layouts — a board that changes
 * shape depending on which of the three it is makes the difference harder to
 * read, not easier.
 *
 * Lifted out of `components/overview/AdvancedHeatmap.tsx` when the BIST boards
 * needed the same three states on ten pages.
 */
export default function StatusMessage({ icon: Icon, children, action }: StatusMessageProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <Icon className="h-4 w-4 text-fg-muted" aria-hidden="true" />
      <p className="max-w-md text-sm text-fg-muted">{children}</p>
      {action}
    </div>
  );
}
