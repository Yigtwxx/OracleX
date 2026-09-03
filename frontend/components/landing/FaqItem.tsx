'use client';

interface FaqItemProps {
  id: string;
  question: string;
  answer: readonly string[];
  open: boolean;
  onToggle: (id: string) => void;
}

/**
 * One question, and its answer behind a controlled disclosure.
 *
 * Not `<details>`, for two reasons. It hides its content with `display: none`,
 * which has no transitionable state — and `::details-content` is not something
 * that can be relied on yet. And the open set has to live in React anyway, since
 * the tally in the rail counts it.
 *
 * The `id` sits on the heading so `/faq#slug` lands on the question rather than
 * on the answer, and the `.landing [id]` rule already clears the fixed header.
 */
export default function FaqItem({ id, question, answer, open, onToggle }: FaqItemProps) {
  return (
    <div className="border-b border-line last:border-b-0">
      <h3 id={id}>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-answer`}
          onClick={() => onToggle(id)}
          className="flex w-full items-start gap-4 py-4 text-left text-md text-fg transition-colors hover:text-fg"
        >
          <span className="flex-1">{question}</span>
          <span aria-hidden="true" className="landing-plus mt-1.5" data-open={open || undefined} />
        </button>
      </h3>

      <div
        id={`${id}-answer`}
        role="region"
        aria-labelledby={id}
        className="landing-disclosure"
        data-open={open || undefined}
      >
        {/* `min-h-0` is what lets the row actually collapse: a grid item's
            automatic minimum size is its content, which would pin it open. */}
        <div className="min-h-0 overflow-hidden">
          <div className="pb-5 pr-8">
            {answer.map((paragraph, i) => (
              <p key={paragraph} className={`text-md text-fg-muted ${i > 0 ? 'mt-3' : ''}`}>
                {paragraph}
              </p>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
