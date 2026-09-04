import { Info } from 'lucide-react';

/**
 * The one place a chart that cannot be drawn is drawn.
 *
 * Every panel on this board keeps its frame when its data is missing and puts
 * this inside it. An empty chart area — axes with nothing on them, or a panel
 * that vanishes from the grid — reads as a page that failed to load, and the
 * reader's next move is to reload rather than to understand that a bank has no
 * EBITDA line. Saying so in a sentence is cheaper than that misunderstanding.
 */
export default function AbsentPanel({ children }: { children: string }) {
  return (
    <div className="flex min-h-[180px] items-center justify-center px-6 py-8">
      <p className="flex max-w-sm items-start gap-2 text-center text-2xs leading-relaxed text-fg-subtle">
        <Info className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
        <span className="text-left">{children}</span>
      </p>
    </div>
  );
}
