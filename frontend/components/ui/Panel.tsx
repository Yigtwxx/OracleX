import { ReactNode } from 'react';

interface PanelProps {
  title: string;
  /** Right-aligned slot in the header: countdown, live badge, filter, etc. */
  action?: ReactNode;
  /** Small explanatory note pinned to the bottom edge. */
  footnote?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Standard dashboard panel: header rule, scrollable body, optional footnote.
 * Every dashboard widget goes through this so headers never drift apart.
 */
export default function Panel({ title, action, footnote, children, className = '' }: PanelProps) {
  return (
    <div className={`surface overflow-hidden flex flex-col h-full ${className}`}>
      <div className="shrink-0 px-4 h-10 border-b border-line flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-fg">{title}</h3>
        {action}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">{children}</div>

      {footnote && (
        <div className="shrink-0 px-4 py-2 border-t border-line text-2xs text-fg-subtle text-center">
          {footnote}
        </div>
      )}
    </div>
  );
}

/** Matching skeleton so loading and loaded states share the same footprint. */
export function PanelSkeleton() {
  return <div className="surface h-full shimmer" />;
}
