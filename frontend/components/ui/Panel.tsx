import { ReactNode } from 'react';

interface PanelProps {
  title: string;
  /** Right-aligned slot in the header: countdown, live badge, filter, etc. */
  action?: ReactNode;
  /**
   * Column header for the rows below it.
   *
   * Rendered outside the scroll container on purpose. macOS hands Chrome an
   * overlay scrollbar — `offsetWidth === clientWidth`, so the thumb reserves no
   * width and floats over the content — and an opaque full-width sticky header
   * inside the scroller therefore paints straight over the thumb whenever the
   * two meet at the top. A column header is not scrollable content anyway, so
   * lifting it out of the scroller is both the fix and the truer structure.
   */
  columns?: ReactNode;
  /** Small explanatory note pinned to the bottom edge. */
  footnote?: string;
  children: ReactNode;
  className?: string;
}

/**
 * Standard dashboard panel: header rule, scrollable body, optional footnote.
 * Every dashboard widget goes through this so headers never drift apart.
 */
export default function Panel({
  title,
  action,
  columns,
  footnote,
  children,
  className = '',
}: PanelProps) {
  return (
    <div className={`surface overflow-hidden flex flex-col h-full ${className}`}>
      <div className="shrink-0 px-4 h-10 border-b border-line flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-fg">{title}</h3>
        {action}
      </div>

      {columns && <div className="shrink-0">{columns}</div>}

      {/* Vertical only. `overflow-y: auto` alone is not that: the spec computes a
          `visible` inline axis to `auto` beside a scrolling block axis, so every
          panel could be dragged sideways the moment one row was a few pixels too
          wide — a whole widget shifting under the cursor over a value nobody was
          reaching for. Clipping the inline axis pins the rows to the panel; a
          child that genuinely needs the width (a table, a code block) declares
          its own `overflow-x-auto` and scrolls inside itself. */}
      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden custom-scrollbar">
        {children}
      </div>

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
