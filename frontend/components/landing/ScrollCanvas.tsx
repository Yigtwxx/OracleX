'use client';

import { useEffect, useRef } from 'react';
import { BTC_SERIES } from '@/lib/landing/candle-series';
import { readPalette } from '@/lib/landing/palette';
import { renderScene } from '@/lib/landing/renderer';
import type { NoteRect, NoteTone } from '@/lib/landing/renderer-leaders';
import { sceneAt } from '@/lib/landing/scene';
import type { StageKey } from '@/lib/landing/stages';

interface ScrollCanvasProps {
  /**
   * The element whose scroll span maps to progress 0 → 1. The footer sits
   * outside it on purpose, so the scene finishes before the page does.
   */
  trackRef: React.RefObject<HTMLElement>;
  /**
   * Fired once, after the first frame has actually been painted. `LandingGate`
   * keeps the page covered until then: an empty board that does not answer a
   * scroll is worse than a moment of nothing.
   */
  onReady?: () => void;
}

/** A 4K display at devicePixelRatio 3 would allocate an 11520px backing store. */
const MAX_BACKING_WIDTH = 3200;
/** Candle pitch in CSS pixels — the slot count follows from the viewport width. */
const SLOT_PITCH = 16;
const MIN_SLOTS = 40;
const MAX_SLOTS = 88;
/** Time constants for the exponential approach, in milliseconds. */
const PROGRESS_TAU = 180;
const DOMAIN_TAU = 260;
/** The finished chart sits behind the hero copy on the reduced-motion path. */
const STATIC_ALPHA = 0.5;

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

export default function ScrollCanvas({ trackRef, onReady }: ScrollCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const trackRefStable = useRef(trackRef);
  trackRefStable.current = trackRef;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    const canvas = canvasRef.current;
    const track = trackRefStable.current.current;
    if (!canvas || !track) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let palette = readPalette(canvas);
    let width = 0;
    let height = 0;
    let slots = MIN_SLOTS;
    let raf = 0;
    let running = false;
    let dirty = true;
    let lastTime = 0;
    let firstFrame = true;
    let eased = 0;
    let domainMin = 0;
    let domainMax = 0;
    let domainReady = false;
    let announced = false;
    let disposed = false;

    /** Reported after a frame has been drawn, never before — see `onReady`. */
    const announce = (): void => {
      if (announced) return;
      announced = true;
      onReadyRef.current?.();
    };

    const resize = (): boolean => {
      const cssWidth = canvas.clientWidth;
      const cssHeight = canvas.clientHeight;
      // A 0×0 element means the canvas is display:none or not laid out yet;
      // sizing to it would produce a permanently blank scene.
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
      dirty = true;
      return true;
    };

    const progressOfTrack = (): number => {
      const rect = track.getBoundingClientRect();
      const scrollable = Math.max(rect.height - window.innerHeight, 1);
      return clamp01(-rect.top / scrollable);
    };

    // The panels are static, so the node list is collected once; only their
    // boxes are re-measured per frame. Measuring happens before any canvas work
    // and canvas drawing does not invalidate layout, so this costs one style
    // recalc per frame rather than a read/write thrash.
    const noteNodes = Array.from(document.querySelectorAll<HTMLElement>('[data-note-key]'));

    const noteRects = (): NoteRect[] =>
      noteNodes.flatMap((node) => {
        const key = node.dataset.noteKey as StageKey | undefined;
        if (!key) return [];
        const box = node.getBoundingClientRect();
        // Fully off-screen panels have no wire to draw, and skipping them here
        // keeps the leader loop from reasoning about it.
        if (box.bottom < 0 || box.top > window.innerHeight) return [];
        return [{ key, left: box.left, top: box.top, right: box.right, bottom: box.bottom }];
      });

    /**
     * Stamps each panel with the direction of the bar its wire came from, so it
     * can carry a trace of that bar's colour.
     *
     * Only the scene knows which bar a panel ended up on — it is resolved from
     * the window on screen — so the attribute has to come back out of the render
     * rather than be decided in the markup. Written only on change: this runs
     * inside the RAF loop, and an unconditional write would dirty style every
     * frame for no reason.
     */
    const applied = new Map<StageKey, string>();

    const applyTones = (tones: readonly NoteTone[]): void => {
      for (const { key, tone } of tones) {
        if (applied.get(key) === tone) continue;
        applied.set(key, tone);
        const node = noteNodes.find((n) => n.dataset.noteKey === key);
        if (node) node.dataset.noteTone = tone;
      }
    };

    const drawStatic = (): void => {
      if (!resize() && width < 1) return;
      const state = sceneAt(1, BTC_SERIES, slots);
      renderScene({ ctx, width, height, palette, alpha: STATIC_ALPHA }, state, BTC_SERIES);
      announce();
    };

    const frame = (now: number): void => {
      raf = requestAnimationFrame(frame);
      if (width < 1 && !resize()) return;

      const dt = firstFrame ? 16 : Math.min(now - lastTime, 64);
      lastTime = now;

      const target = progressOfTrack();
      if (firstFrame) {
        // Snapping on the first frame matters: a reload restores the scroll
        // position, and easing up from zero would fast-forward the entire print
        // in about a second every single time.
        eased = target;
        firstFrame = false;
      } else {
        eased += (target - eased) * (1 - Math.exp(-dt / PROGRESS_TAU));
      }

      const state = sceneAt(eased, BTC_SERIES, slots);

      if (!domainReady) {
        domainMin = state.priceMin;
        domainMax = state.priceMax;
        domainReady = true;
      } else {
        // Easing the y-domain rather than snapping it: the first few candles
        // would otherwise be flattened the instant a taller bar prints.
        const k = 1 - Math.exp(-dt / DOMAIN_TAU);
        domainMin += (state.priceMin - domainMin) * k;
        domainMax += (state.priceMax - domainMax) * k;
      }

      const span = Math.max(domainMax - domainMin, 1);
      const settled =
        Math.abs(target - eased) < 1e-4 &&
        Math.abs(state.priceMin - domainMin) / span < 1e-3 &&
        Math.abs(state.priceMax - domainMax) / span < 1e-3;
      if (settled && !dirty) {
        // A settled first frame still counts as running: at the top of the page
        // the scene is deliberately empty, and the gate must not wait for a
        // scroll that will not come until it lifts.
        announce();
        return;
      }
      dirty = false;

      applyTones(
        renderScene(
          { ctx, width, height, palette, alpha: 1 },
          { ...state, priceMin: domainMin, priceMax: domainMax },
          BTC_SERIES,
          noteRects()
        )
      );
      announce();
    };

    const start = (): void => {
      if (running || motion.matches) return;
      running = true;
      lastTime = performance.now();
      raf = requestAnimationFrame(frame);
    };

    const stop = (): void => {
      if (!running) return;
      running = false;
      cancelAnimationFrame(raf);
    };

    const onMotionChange = (): void => {
      if (motion.matches) {
        stop();
        drawStatic();
      } else {
        firstFrame = true;
        domainReady = false;
        dirty = true;
        start();
      }
    };

    const resizeObserver = new ResizeObserver(() => {
      if (!resize()) return;
      if (motion.matches) drawStatic();
    });
    resizeObserver.observe(canvas);

    // Observed on the track, not the canvas: a position:fixed full-viewport
    // canvas is always intersecting, so it can never report going off-screen.
    const visibility = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) start();
        else stop();
      },
      { rootMargin: '0px' }
    );
    visibility.observe(track);

    const onVisibilityChange = (): void => {
      if (document.hidden) stop();
      else if (!motion.matches) start();
    };

    // Canvas text is painted, not laid out: a webfont arriving after a frame
    // has been drawn does not reflow it the way it would reflow the DOM, so the
    // price scale and the callouts would keep their fallback metrics until the
    // next scroll happened to repaint them.
    void document.fonts.ready.then(() => {
      if (disposed) return;
      palette = readPalette(canvas);
      dirty = true;
      if (motion.matches) drawStatic();
    });

    resize();
    if (motion.matches) drawStatic();
    else start();

    motion.addEventListener('change', onMotionChange);
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      disposed = true;
      stop();
      resizeObserver.disconnect();
      visibility.disconnect();
      motion.removeEventListener('change', onMotionChange);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0">
      {/* Under the canvas rather than over it: the tape is drawn onto a cleared,
          transparent surface, so an ambient wash sitting behind it lights the
          page without touching a single candle. */}
      <div className="landing-glow absolute inset-0" />
      <canvas ref={canvasRef} className="h-full w-full" />
      {/* Keeps copy legible over the tape without dimming the scene itself. */}
      <div className="landing-scrim absolute inset-0" />
    </div>
  );
}
