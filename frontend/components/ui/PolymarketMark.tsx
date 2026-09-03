'use client';

import { useId } from 'react';

/**
 * Polymarket's own mark, redrawn onto lucide's 24×24 canvas.
 *
 * The geometry is the real logo rather than an approximation of it: the outer
 * shell and the three chevrons are the vendor's own path data, rescaled from its
 * native 136×167 box to sit at the same optical size as the lucide icons beside
 * it (fitted to 20 units tall, centred, leaving the 2-unit margin the rest of
 * the set draws within).
 *
 * **Why a mask rather than one path.** In the original the three chevrons are
 * subpaths of a single shape, punched out by the nonzero fill rule. That renders
 * perfectly and animates not at all — there are no separate elements to move,
 * and splitting the subpaths into their own `<path>` elements fills the holes
 * in, which is a different logo. Painting the shell into a luminance mask puts
 * each chevron back into its own element while leaving the rendered result
 * pixel-identical to the single-path version.
 *
 * A useful side effect: in the mask, a chevron at `opacity: 0` is a hole that
 * has not been cut yet, so the gesture in globals.css can start from a solid
 * block and resolve it into the mark — the shape assembling itself rather than
 * merely arriving.
 *
 * The mask id comes from `useId` because an id is document-scoped: two of these
 * on one page with a hardcoded id would both reference whichever mask rendered
 * first, and the second would silently inherit the first one's animation state.
 */
interface PolymarketMarkProps {
  className?: string;
}

export default function PolymarketMark({ className }: PolymarketMarkProps) {
  const maskId = useId();

  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
        <path
          fill="#fff"
          d="M20.161 20.265C20.161 21.134 20.161 21.569 19.877 21.784C19.593 22 19.174 21.883 18.337 21.648L4.887 17.873C4.382 17.732 4.13 17.661 3.984 17.469C3.839 17.276 3.839 17.014 3.839 16.491V7.645C3.839 7.121 3.839 6.859 3.984 6.667C4.13 6.475 4.382 6.404 4.887 6.262L18.337 2.488C19.174 2.253 19.593 2.136 19.877 2.351C20.161 2.567 20.161 3.001 20.161 3.871V20.265Z"
        />
        {/* Chevrons bottom, middle, top — the order the gesture's :nth-child
            selectors depend on. Bottom and top point left, the middle points
            right, which is what the gesture reads off. */}
        <path fill="#000" d="M7.193 16.643L18.33 19.768V13.517L7.193 16.643Z" />
        <path fill="#000" d="M5.67 15.193L16.805 12.068L5.67 8.943V15.193Z" />
        <path fill="#000" d="M7.193 7.493L18.33 10.618V4.367L7.193 7.493Z" />
      </mask>
      {/* currentColor so the tab's --nav-tint reaches it exactly as it reaches
          a stroked lucide icon. */}
      <rect
        className="pm-fill"
        width="24"
        height="24"
        fill="currentColor"
        mask={`url(#${maskId})`}
      />

      {/*
        The pen. Invisible at rest and only ever drawn during the hover gesture
        in globals.css, where each of these is walked with stroke-dashoffset.

        These are centrelines, not outlines, and that distinction is the whole
        point. This mark is not a filled shape that happens to look linear — it
        *is* a constant-width stroke drawing: measured, the border band runs 1.83
        units and both interior bands 1.81. Tracing the boundaries instead drew
        each solid band from both sides at once, so a band that should read as
        one line came out hollow with an edge either side of it, and every stroke
        was thinner than the finished artwork. Running down the middle at the
        band's own width reproduces the mark rather than outlining it, and the
        drawn state and the filled state become the same picture.

        Two strokes, top to bottom: the frame, then one unbroken zigzag that
        leaves the left wall, crosses to the right, steps down and comes back.
        The frame is a plain quadrilateral because at this size its rounded
        corners are a pixel across and `stroke-linejoin: round` supplies them.
      */}
      <g
        className="pm-ink"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.83}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M4.78 7.3L19.25 3.35L19.25 20.7L4.78 16.75Z" />
        <path d="M4.78 7.76L17.57 11.34L17.57 12.79L4.78 16.38" />
      </g>
    </svg>
  );
}
