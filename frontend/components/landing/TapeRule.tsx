'use client';

import { useEffect, useRef } from 'react';
import { BTC_SERIES } from '@/lib/landing/candle-series';
import { readPalette, withAlpha } from '@/lib/landing/palette';

/** How long the whole strip takes to arrive. */
const PRINT_MS = 900;
/** The exponential's time constant — front-loads the fill, then trickles. */
const PRINT_TAU = 300;

/** Horizontal sampling, in CSS pixels per point. Dense enough to read smooth. */
const STEP = 4;
const MIN_POINTS = 60;
const MAX_POINTS = 260;

/** Vertical inset, so the extremes of the window are not clipped. */
const PAD = 6;

const LINE_WIDTH = 1.5;
const LINE_ALPHA = 0.85;
/** The area under the line, at the line and at the baseline. */
const FILL_TOP_ALPHA = 0.16;

interface TapeRuleProps {
  height?: number;
}

/**
 * The tape across the masthead, drawn as a line.
 *
 * It was candles first, and candles were wrong here for a reason worth writing
 * down: body height is the bar's open-to-close as a fraction of the window's
 * whole range, and in a band this short that fraction rounds to a pixel for
 * every bar on screen. Narrowing the window to fatten the bodies only widened
 * the pitch until the strip read as a picket fence. A line has no such
 * constraint — it uses the full height at any density — and it is still the same
 * series the landing page prints, so the two pages remain the same board.
 *
 * Time-driven rather than scroll-driven. The masthead is above the fold on every
 * viewport, so there is no scroll to drive it, and a rule that filled as you
 * scrolled past it would be finished before it had been looked at. It prints
 * once and then stops: the RAF is cancelled on the last frame rather than left
 * idling, because nothing on this page needs a loop after that.
 */
export default function TapeRule({ height = 64 }: TapeRuleProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // The sweep is a RAF loop, which the global reduced-motion CSS rule cannot
    // reach — it only collapses declared animations and transitions. So this
    // reads the query itself, the way `GoTerminalButton` has to.
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let palette = readPalette(canvas);
    let width = 0;
    let points = MIN_POINTS;
    let raf = 0;
    let started = 0;
    let disposed = false;

    const resize = (): boolean => {
      const cssWidth = canvas.clientWidth;
      if (cssWidth < 1) return false;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(cssWidth * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      width = cssWidth;
      points = Math.max(MIN_POINTS, Math.min(MAX_POINTS, Math.floor(cssWidth / STEP)));
      palette = readPalette(canvas);
      return true;
    };

    /** `progress` is the fraction of the strip that has printed. */
    const draw = (progress: number): void => {
      if (width < 1 && !resize()) return;
      ctx.clearRect(0, 0, width, height);

      const candles = BTC_SERIES.candles;
      const count = Math.min(points, candles.length);
      // The tail: the most recent stretch of tape, which is the one a board
      // would be showing. A line renders a trending window perfectly well, so
      // unlike the candle version there is nothing to be gained by hunting for
      // a flat stretch of the series.
      const window_ = candles.slice(candles.length - count);

      let low = Infinity;
      let high = -Infinity;
      for (const candle of window_) {
        if (candle.c < low) low = candle.c;
        if (candle.c > high) high = candle.c;
      }
      const span = Math.max(high - low, 1e-6);

      const usable = height - PAD * 2;
      const x = (i: number): number => (i / (window_.length - 1)) * width;
      const y = (price: number): number => PAD + (1 - (price - low) / span) * usable;

      const drawn = Math.max(2, Math.round(window_.length * progress));
      const rising = window_[drawn - 1].c >= window_[0].c;
      const tone = rising ? palette.up : palette.down;

      // The area first, so the line sits on top of its own fill rather than
      // being half-covered by it where the two meet.
      const gradient = ctx.createLinearGradient(0, 0, 0, height);
      gradient.addColorStop(0, withAlpha(tone, FILL_TOP_ALPHA));
      gradient.addColorStop(1, withAlpha(tone, 0));
      ctx.fillStyle = gradient;
      ctx.beginPath();
      ctx.moveTo(x(0), height);
      for (let i = 0; i < drawn; i += 1) ctx.lineTo(x(i), y(window_[i].c));
      ctx.lineTo(x(drawn - 1), height);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = withAlpha(tone, LINE_ALPHA);
      ctx.lineWidth = LINE_WIDTH;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x(0), y(window_[0].c));
      for (let i = 1; i < drawn; i += 1) ctx.lineTo(x(i), y(window_[i].c));
      ctx.stroke();

      // The write head, and only while there is still tape to come. Leaving it
      // on the last point would turn a finished strip into a cursor waiting for
      // input that never arrives.
      if (drawn < window_.length) {
        const tipX = x(drawn - 1);
        const tipY = y(window_[drawn - 1].c);
        ctx.strokeStyle = withAlpha(palette.accent, 0.35);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(tipX, PAD);
        ctx.lineTo(tipX, height - PAD);
        ctx.stroke();

        ctx.fillStyle = palette.accent;
        ctx.beginPath();
        ctx.arc(tipX, tipY, 2, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const step = (now: number): void => {
      if (!started) started = now;
      const elapsed = now - started;
      // Eased rather than linear: a linear print spends its first third looking
      // like an empty rule, which reads as a rendering fault at this size.
      const progress = Math.min(1, 1 - Math.exp(-elapsed / PRINT_TAU));
      draw(progress);

      if (elapsed >= PRINT_MS) {
        draw(1);
        raf = 0;
        return;
      }
      raf = requestAnimationFrame(step);
    };

    const start = (): void => {
      if (raf || motion.matches) return;
      started = 0;
      raf = requestAnimationFrame(step);
    };

    const resizeObserver = new ResizeObserver(() => {
      if (!resize()) return;
      // Mid-print, the next frame redraws at the new width on its own. Once it
      // has finished there is no loop left to do it.
      if (!raf) draw(1);
    });
    resizeObserver.observe(canvas);

    void document.fonts.ready.then(() => {
      if (disposed || raf) return;
      palette = readPalette(canvas);
      draw(1);
    });

    resize();

    const onMotionChange = (): void => {
      if (!motion.matches) return;
      cancelAnimationFrame(raf);
      raf = 0;
      draw(1);
    };
    motion.addEventListener('change', onMotionChange);

    if (motion.matches) draw(1);
    else start();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      resizeObserver.disconnect();
      motion.removeEventListener('change', onMotionChange);
    };
  }, [height]);

  return (
    <canvas ref={canvasRef} aria-hidden="true" className="landing-tape w-full" style={{ height }} />
  );
}
