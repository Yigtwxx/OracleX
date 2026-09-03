import type { ReactNode } from 'react';

interface BistChartPanelProps {
  title: string;
  /** What the panel's axes or channels encode. Sits under the title, always on. */
  legend: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}

/**
 * One chart panel on a `/bist` board.
 *
 * Named for what it is rather than for the page it was written on: the
 * positioning board and the VİOP board both draw four of these, and a shell
 * living under `positioning/` that the derivatives page imported would be a
 * dependency nobody could explain a month later.
 *
 * Not `ui/Panel`: that one scrolls its body and carries the lit `.surface` rim.
 * Neither suits a chart. A chart sized to its container has nothing to scroll,
 * and the rim is painted with `background-attachment: fixed`, which Safari
 * re-rasterises on every scroll tick — fine on a handful of cards, and the
 * reason a dense grid of them stutters. `.surface-flat` drops it.
 *
 * The legend is a required prop rather than an optional one because every panel
 * using it encodes at least two quantities at once — bubble size against
 * colour, bar height against tint, a settlement curve against its own front
 * month. A reader who has to guess what a channel means is reading a
 * decoration.
 */
export default function BistChartPanel({ title, legend, action, children }: BistChartPanelProps) {
  return (
    <section className="surface surface-flat flex flex-col overflow-hidden">
      <header className="flex shrink-0 items-start justify-between gap-3 border-b border-line px-3 py-2">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-fg">{title}</h2>
          <p className="mt-0.5 text-2xs text-fg-subtle">{legend}</p>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}
