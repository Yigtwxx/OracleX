interface FigureFrameProps {
  /** The mono micro-label. Says what is being counted, never how impressive it is. */
  eyebrow: string;
  children: React.ReactNode;
  /** The line under the figure. Numbers or a qualification, not a caption. */
  footnote?: React.ReactNode;
}

/**
 * The panel every margin figure sits in.
 *
 * Shared because the eyebrow-and-dashed-rule header is the page's one repeated
 * gesture, and six copies of it would drift into six. `.landing-note` rather
 * than `.landing-plate`: these are the objects the prose is pointing at, and the
 * corner brackets are what say so.
 */
export default function FigureFrame({ eyebrow, children, footnote }: FigureFrameProps) {
  return (
    <figure className="landing-note p-5">
      <div className="mb-4 flex items-center gap-2.5">
        <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
          {eyebrow}
        </span>
        <span className="flex-1 border-t border-dashed border-line" />
      </div>

      {children}

      {footnote && (
        <figcaption className="mt-4 border-t border-dashed border-line pt-3 font-mono text-2xs leading-relaxed text-fg-subtle">
          {footnote}
        </figcaption>
      )}
    </figure>
  );
}
