interface AnsweredTallyProps {
  /** One entry per question, in order: true once it has been opened. */
  marks: readonly boolean[];
}

/**
 * The reader's own progress, printed as a tape.
 *
 * The right rail on `/developers` is generated figures; there are none to show
 * here, and filling the space with a decorative loop would be motion for its own
 * sake. So this is driven by the one thing that is genuinely happening on the
 * page: a mark lights when its question is opened. Nothing runs on a timer.
 */
export default function AnsweredTally({ marks }: AnsweredTallyProps) {
  const opened = marks.filter(Boolean).length;

  return (
    <div>
      <p className="font-mono text-2xs tabnum text-fg-subtle">
        opened <span className="text-fg">{opened}</span> / {marks.length}
      </p>

      <div aria-hidden="true" className="mt-2 flex flex-wrap gap-1">
        {marks.map((on, i) => (
          <span key={i} className="landing-tick" data-on={on ? '' : undefined} />
        ))}
      </div>
    </div>
  );
}
