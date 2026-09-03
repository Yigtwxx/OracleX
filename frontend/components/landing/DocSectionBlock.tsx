import Reveal from './Reveal';
import type { DocSection } from '@/lib/marketing/sections';

interface DocSectionBlockProps {
  section: DocSection;
  /**
   * The margin figure. A node rather than a render prop: functions do not cross
   * the server/client boundary, and these pages keep `page.tsx` on the server so
   * it can still export `metadata`.
   */
  figure?: React.ReactNode;
  /** Anything that belongs under the prose rather than beside it — a code block. */
  children?: React.ReactNode;
}

/**
 * One section: prose in the reading column, its figure in the right rail.
 *
 * The figure is `sticky`, so it holds while its own section is being read and is
 * pushed out by the next one through ordinary scrolling — no swap machinery, no
 * reserved height, and nothing that can jump.
 *
 * Below `xl` there is no rail and the figure reflows underneath the prose rather
 * than being hidden. Every figure here is a generated number, and dropping them
 * on a phone would leave the argument with nothing under it.
 */
export default function DocSectionBlock({ section, figure, children }: DocSectionBlockProps) {
  return (
    <section
      id={section.id}
      data-doc-section=""
      aria-labelledby={`${section.id}-heading`}
      className="grid scroll-mt-16 gap-x-10 gap-y-8 py-14 xl:grid-cols-[minmax(0,1fr)_300px]"
    >
      <div>
        <Reveal>
          <div className="mb-4 flex items-center gap-2.5">
            <span className="font-mono text-2xs tabnum text-fg-subtle">{section.index}</span>
            <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
              {section.label}
            </span>
            <span className="flex-1 border-t border-dashed border-line" />
          </div>

          <h2
            id={`${section.id}-heading`}
            className="text-display-2 font-semibold tracking-tight text-fg"
          >
            {section.title}
          </h2>

          {section.body.map((paragraph) => (
            <p key={paragraph} className="mt-4 text-md text-fg-muted">
              {paragraph}
            </p>
          ))}

          {children}
        </Reveal>
      </div>

      {figure && (
        <div className="xl:sticky xl:top-[5.5rem] xl:self-start">
          <Reveal delay={80}>{figure}</Reveal>
        </div>
      )}
    </section>
  );
}
