import DocRail, { type RailItem } from './DocRail';

interface DocPageProps {
  masthead: React.ReactNode;
  /** Drives the spine. Must match the sections rendered as children. */
  sections: readonly RailItem[];
  children: React.ReactNode;
}

/**
 * The reading shell: a spine on the left, a column in the middle, and whatever
 * each section hangs in the right rail.
 *
 * Three breakpoints rather than two. Below `lg` it is one column, because a
 * spine and a figure rail on a phone would leave the prose about twenty
 * characters wide. At `lg` the spine arrives. At `xl` the figure rail does, and
 * the reading column narrows to make room rather than the page growing — a
 * measure that keeps widening as the viewport does stops being a measure.
 *
 * The reading area carries its own opaque ground. The spine keeps the board
 * behind it, which is what stops the page reading as a document that happens to
 * have been pasted over a chart: the tape runs down the margin, and the prose
 * has somewhere solid to sit.
 */
export default function DocPage({ masthead, sections, children }: DocPageProps) {
  return (
    <main className="mx-auto w-full max-w-[1400px] px-6 pb-24 sm:px-10 lg:px-16">
      <div className="lg:grid lg:grid-cols-[184px_minmax(0,1fr)] lg:gap-x-10">
        {/* Empty in the masthead's row: the spine tracks the sections, and a
            marker sitting beside the title would be pointing at nothing. */}
        <div aria-hidden="true" className="hidden lg:block" />
        <div className="relative min-w-0">
          <div aria-hidden="true" className="landing-read" />
          <div className="relative">{masthead}</div>
        </div>

        <DocRail sections={sections} />
        <div className="relative min-w-0">
          <div aria-hidden="true" className="landing-read" />
          <div className="relative">{children}</div>
        </div>
      </div>
    </main>
  );
}
