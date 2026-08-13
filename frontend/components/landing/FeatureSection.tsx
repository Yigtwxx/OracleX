import { figureOf } from '@/lib/landing/imagery';
import type { Feature } from '@/lib/landing/stages';
import Reveal from './Reveal';
import StageFigure from './StageFigure';
import TypedPoints from './TypedPoints';

interface FeatureSectionProps {
  feature: Feature;
  /** Section height in viewport heights, from the stage schedule. */
  vh: number;
  /**
   * Dropped into the empty upper third of the stage, above the panel.
   *
   * Absolutely positioned, so it cannot make the section taller than the stage
   * schedule says it is — which is what keeps the canvas and the document the
   * same length. Only the analysis stage passes anything.
   */
  overlay?: React.ReactNode;
}

/**
 * One panel of copy, written as a note left on the tape rather than as a
 * marketing block.
 *
 * `data-note-key` is what the canvas looks for: it measures this element every
 * frame and draws the dotted leader from the panel's candle to its edge. The
 * panel never positions the wire itself — a DOM stub could only guess where the
 * bar is, and the bar moves.
 *
 * Copy upper-left, picture lower-right, and identically in every stage — which
 * is the only arrangement that alternates in both directions at once.
 *
 * Each stage contributes two things, on opposite sides and in opposite halves.
 * Read down the page that is left, right, left, right and copy, picture, copy,
 * picture — but only while the arrangement is fixed. Flip either axis per stage
 * and the flipped one lines up two of the same thing across the seam: reversing
 * the sides puts two panels in the same column, reversing the halves puts two
 * pictures back to back. There is no arrangement that alternates one axis per
 * stage and still alternates the other.
 *
 * Splitting the halves is also what keeps the page from stalling: each stage
 * covers its own height rather than stacking both items in the middle, so the
 * empty board between one stage and the next is about a third of a screen
 * instead of most of one.
 */
export default function FeatureSection({ feature, vh, overlay }: FeatureSectionProps) {
  const headingId = `feature-${feature.key}`;
  const figure = figureOf(feature.key);

  return (
    <section
      aria-labelledby={headingId}
      style={{ minHeight: `${vh}svh` }}
      // The vertical inset is padding on a still-`minHeight`-bound section
      // rather than a translate or a taller box: the stage schedule and the
      // canvas share this number, and a section that grows by an inch puts the
      // whole scene out of step with the copy it is annotating.
      //
      // Only above `lg`: below it there is no picture to sit opposite, so a
      // lifted panel would leave the space it vacated genuinely empty.
      className="relative flex items-center justify-start px-6 sm:px-10 lg:items-start lg:px-16 lg:pt-[24svh]"
    >
      {figure && <StageFigure figure={figure} align="low" />}

      {/* Stacked above the figure in the same column, not centred in the stage:
          centred, it sat between the two columns and belonged to neither. The
          gutter matches `StageFigure` exactly so the two line up as one stack.

          The negative offset lifts it clear of the stage's own top edge into the
          empty band the previous section leaves behind — the gap this was added
          to fill starts above this section, not inside it. Absolute, so it
          cannot pull either section's height with it. */}
      {overlay && (
        <div className="absolute inset-x-0 -top-[12%] hidden justify-end pr-28 lg:flex">
          {overlay}
        </div>
      )}

      <Reveal data-note-key={feature.key} className="landing-note w-full max-w-md p-5 sm:p-6">
        <div className="mb-4 flex items-center gap-2.5">
          <span className="font-mono text-2xs tabnum tracking-[0.08em] text-accent">
            {feature.index}
          </span>
          <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
            {feature.eyebrow}
          </span>
          <span className="flex-1 border-t border-dashed border-line" />
        </div>

        <h2 id={headingId} className="text-2xl font-semibold leading-tight tracking-tight text-fg">
          {feature.title}
        </h2>

        <div className="mt-3 space-y-3">
          {feature.body.map((paragraph) => (
            <p key={paragraph} className="text-md text-fg-muted">
              {paragraph}
            </p>
          ))}
        </div>

        <TypedPoints
          items={feature.points}
          className="mt-5 space-y-2"
          itemClassName="flex items-start gap-2.5 text-base text-fg"
        />

        <dl className="mt-5 flex flex-wrap gap-x-6 gap-y-2 border-t border-dashed border-line pt-4">
          {feature.metrics.map((metric) => (
            <div key={metric.label} className="flex items-baseline gap-1.5">
              <dt className="sr-only">{metric.label}</dt>
              <dd className="font-mono text-md tabnum font-semibold text-fg">{metric.value}</dd>
              <span aria-hidden="true" className="font-mono text-2xs text-fg-subtle">
                {metric.label}
              </span>
            </div>
          ))}
        </dl>
      </Reveal>
    </section>
  );
}
