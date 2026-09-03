'use client';

import { useEffect, useRef } from 'react';
import { BTC_SERIES } from '@/lib/landing/candle-series';
import { readPalette } from '@/lib/landing/palette';
import { renderTape } from '@/lib/landing/renderer';
import { sceneAt } from '@/lib/landing/scene';

/** A 4K display at devicePixelRatio 3 would allocate an 11520px backing store. */
const MAX_BACKING_WIDTH = 3200;
/** Candle pitch in CSS pixels — the slot count follows from the viewport width. */
const SLOT_PITCH = 16;
const MIN_SLOTS = 40;
const MAX_SLOTS = 88;

/**
 * Quieter than the landing page's own static frame. There the tape is the
 * subject; here it is behind a column of prose that has to stay readable.
 */
const BACKDROP_ALPHA = 0.3;

/**
 * The same board as the landing page, finished and standing still.
 *
 * A copy of `ScrollCanvas` rather than a mode of it. That component's whole
 * subject is the relationship between a scroll position and a print, and
 * threading a `static` flag through it would leave the most load-bearing piece
 * of the landing page carrying a branch that neither its comments nor its tests
 * describe. The two share everything that actually matters — the series, the
 * palette, the scene and the renderer all live in `lib/landing/` — and what is
 * duplicated here is the twenty lines of canvas bookkeeping that differ.
 *
 * What is deliberately absent: the RAF loop, the eased progress and y-domain,
 * the track observer and the `visibilitychange` handler — and the annotations.
 * It draws through `renderTape` rather than `renderScene`, because the full
 * scene carries eight pattern callouts, a price scale and a last-price tag, and
 * every one of those is a piece of type competing with the paragraph sitting on
 * top of it. Turning the alpha down far enough to fix that took the tape down
 * with it; taking the annotations off fixes it at any alpha.
 */
export default function StaticBackdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Read from the canvas rather than from the document root: these pages
    // render inside the marketing layout's `.landing` scope, which overrides
    // the accent to white. Reading `:root` would paint the terminal's blue.
    let palette = readPalette(canvas);
    let width = 0;
    let height = 0;
    let slots = MIN_SLOTS;
    let disposed = false;

    const resize = (): boolean => {
      const cssWidth = canvas.clientWidth;
      const cssHeight = canvas.clientHeight;
      if (cssWidth < 1 || cssHeight < 1) return false;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const scale = Math.min(dpr, MAX_BACKING_WIDTH / cssWidth);
      canvas.width = Math.round(cssWidth * scale);
      canvas.height = Math.round(cssHeight * scale);
      // Resizing the backing store resets the context, so the transform has to
      // be reapplied here rather than once at setup.
      ctx.setTransform(scale, 0, 0, scale, 0, 0);

      width = cssWidth;
      height = cssHeight;
      slots = Math.max(MIN_SLOTS, Math.min(MAX_SLOTS, Math.round(cssWidth / SLOT_PITCH)));
      palette = readPalette(canvas);
      return true;
    };

    const draw = (): void => {
      if (!resize() && width < 1) return;
      const state = sceneAt(1, BTC_SERIES, slots);
      renderTape({ ctx, width, height, palette, alpha: BACKDROP_ALPHA }, state, BTC_SERIES);
    };

    const resizeObserver = new ResizeObserver(draw);
    resizeObserver.observe(canvas);

    // Canvas text is painted, not laid out: a webfont arriving after the frame
    // has been drawn does not reflow it the way it would reflow the DOM, so the
    // price scale would keep its fallback metrics for the life of a page that
    // never repaints on its own.
    void document.fonts.ready.then(() => {
      if (disposed) return;
      palette = readPalette(canvas);
      draw();
    });

    draw();

    return () => {
      disposed = true;
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0">
      <div className="landing-glow absolute inset-0" />
      <canvas ref={canvasRef} className="h-full w-full" />
      <div className="landing-scrim absolute inset-0" />
    </div>
  );
}
