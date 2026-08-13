import type { CSSProperties } from 'react';
import type { StageFigure as Figure } from '@/lib/landing/imagery';

interface StageFigureProps {
  figure: Figure;
  /**
   * Where in the stage to hang it.
   *
   * `low` is the feature stages: the copy panel takes the upper half, so the two
   * of them span the section instead of stacking in the middle of it and leaving
   * a screen of nothing above and below.
   *
   * `center` is the print band, which runs two copy beats rather than one and
   * wants its picture in the gap between them — that is the slot that keeps the
   * page alternating picture, copy, picture, copy all the way down.
   */
  align?: 'center' | 'low';
}

/**
 * The ghost picture opposite a copy panel — always the right column, because
 * the copy is always the left one. Fixing the two columns is what lets the page
 * alternate left, right, left, right down the scroll; see `FeatureSection`.
 *
 * Painted as a background image on an empty div rather than as an `<img>`, for
 * two reasons that both matter more than the house style it departs from. An
 * element with `display: none` never issues the request, which is how the whole
 * set stays off mobile where there is no room for it; and a background has no
 * intrinsic size to wait for, so the box is whatever the aspect ratio says from
 * the first frame and nothing moves when the bytes land. It is also honestly
 * decorative — there is no `alt` text that would be true, and this way there is
 * no place to put one.
 *
 * Deliberately not inside the `Reveal`: that element is measured every frame by
 * the canvas to find where the leader wire attaches, and growing it would drag
 * the wire along with it.
 */
export default function StageFigure({ figure, align = 'center' }: StageFigureProps) {
  return (
    <div
      aria-hidden="true"
      // `right-28` rather than the page's own inset: the canvas keeps a 78px
      // gutter on this edge for its price scale, and the picture has to stop
      // short of it or it sits on the axis.
      className={`landing-figure pointer-events-none absolute right-28 -translate-y-1/2 ${
        align === 'center' ? 'top-1/2' : 'top-[70%]'
      }`}
      style={
        {
          '--figure-src': `url(${figure.src})`,
          aspectRatio: `${figure.width} / ${figure.height}`,
        } as CSSProperties
      }
    >
      {/* The photograph is a child rather than a pseudo-element so the frame can
          keep both of its own — the two corner brackets, which have to stay at
          full strength while the picture inside them is faded. */}
      <span className="landing-figure-plate" />
    </div>
  );
}
