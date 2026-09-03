'use client';

import { useEffect, useRef } from 'react';
import {
  CHAIN_BOXES,
  CHAIN_FLOWS,
  CHAIN_STAMPS,
  CHAIN_SUMMARY,
  CHAIN_VIEW,
  phasesAt,
  type ChainBox,
  type ChainPhases,
  type Point,
} from '@/lib/landing/chain';
import { clamp01 } from '@/lib/landing/ramp';
import { readPalette, withAlpha } from '@/lib/landing/palette';
import { LLM } from '@/lib/generated/repo-facts';

/** CSS size of the drawing surface. It lives in the figure rail, so it is tall. */
const WIDTH = 258;
const HEIGHT = 320;
/** Time constant for the exponential approach, in milliseconds. */
const TAU = 190;

/** Which phase drives which box, in `CHAIN_BOXES` order. */
const BOX_PHASES: readonly (keyof ChainPhases)[] = [
  'request',
  'prefer',
  'local',
  'hosted',
  'answered',
  'reply',
];

/** Which phase drives which flow segment, in `CHAIN_FLOWS` order. */
const FLOW_PHASES: readonly (keyof ChainPhases)[] = [
  'toLocal',
  'toHosted',
  'toAnswered',
  'toReply',
];

/**
 * The provider chain, descending.
 *
 * The one thing on these pages that earns a canvas. A fallback chain has a
 * sequence and a failure branch — the request enters, a provider declines, a
 * cooldown is stamped on it, the request steps down, the next one answers — and
 * that is four clauses of prose against one glance. The health registry, by
 * contrast, is a list of things and is drawn as a list.
 *
 * Structurally a clone of `PassDiagram`: its own progress from its own box, an
 * exponential approach, an intersection observer to start and stop it, and the
 * finished diagram rather than an empty card under reduced motion. The geometry
 * lives in `lib/landing/chain.ts` so the shape can be changed without opening
 * any of this.
 */
export default function ChainDiagram() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let palette = readPalette(canvas);
    let raf = 0;
    let running = false;
    let eased = 0;
    let lastTime = 0;
    let first = true;

    const resize = (): void => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(WIDTH * dpr);
      canvas.height = Math.round(HEIGHT * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      palette = readPalette(canvas);
    };

    const progress = (): number => {
      const box = canvas.getBoundingClientRect();
      const vh = window.innerHeight;
      return clamp01((vh * 0.86 - box.top) / (vh * 0.5));
    };

    const draw = (p: number): void => {
      const scale = Math.min(WIDTH / CHAIN_VIEW.width, HEIGHT / CHAIN_VIEW.height);
      const originX = (WIDTH - CHAIN_VIEW.width * scale) / 2;
      const originY = (HEIGHT - CHAIN_VIEW.height * scale) / 2;
      // Converted to pixels rather than drawn under a canvas transform, so the
      // type stays on whole pixels and the hairlines stay hairlines.
      const px = (x: number): number => originX + x * scale;
      const py = (y: number): number => originY + y * scale;

      const phase = phasesAt(p);
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';

      const toneOf = (box: ChainBox): string => {
        if (box.outcome === 'answered') return palette.up;
        if (box.outcome === 'declined') return palette.down;
        return palette.accent;
      };

      const strokeFlow = (points: readonly Point[], t: number): void => {
        if (t <= 0) return;
        const from = { x: px(points[0].x), y: py(points[0].y) };
        const to = { x: px(points[1].x), y: py(points[1].y) };
        const tip = { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t };

        ctx.strokeStyle = withAlpha(palette.fgMuted, 0.7);
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(tip.x, tip.y);
        ctx.stroke();
        ctx.setLineDash([]);

        // The head only once the segment has arrived. A head travelling with
        // the tip reads as a cursor rather than as a direction.
        if (t < 0.98) return;
        ctx.fillStyle = withAlpha(palette.fgMuted, 0.85);
        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(to.x - 4, to.y - 5);
        ctx.lineTo(to.x + 4, to.y - 5);
        ctx.closePath();
        ctx.fill();
      };

      const drawBox = (box: ChainBox, alpha: number): void => {
        if (alpha <= 0) return;
        const x = px(box.x);
        const y = py(box.y);
        const w = box.width * scale;
        const h = box.height * scale;
        const tone = toneOf(box);

        ctx.fillStyle = withAlpha(palette.surface, alpha * 0.92);
        ctx.fillRect(x, y, w, h);

        ctx.strokeStyle = withAlpha(tone, alpha * 0.8);
        ctx.lineWidth = 1;
        // Dashed for the box that is only there when the caller asked for it —
        // a solid outline would say the chain always has a preferred provider.
        if (box.optional) ctx.setLineDash([3, 3]);
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
        ctx.setLineDash([]);

        if (!box.optional) {
          // The same left spine the annotation panels on the tape carry.
          ctx.fillStyle = withAlpha(tone, alpha * 0.85);
          ctx.fillRect(x, y, 2, h);
        }

        ctx.textBaseline = 'alphabetic';
        ctx.textAlign = 'left';
        ctx.font = `600 10px ${palette.mono}`;
        ctx.fillStyle = withAlpha(palette.fg, alpha);
        ctx.fillText(box.title, x + 8, y + (box.detail ? 14 : 16));

        if (box.detail) {
          ctx.font = `400 9px ${palette.mono}`;
          ctx.fillStyle = withAlpha(tone, alpha * 0.9);
          ctx.fillText(box.detail, x + 8, y + 26);
        }
      };

      const drawStamp = (
        stamp: (typeof CHAIN_STAMPS)[number],
        alpha: number
      ): void => {
        const shown = clamp01((alpha - 0.55) / 0.45);
        if (shown <= 0) return;
        const x = px(stamp.x);
        const y = py(stamp.y);
        const w = stamp.width * scale;
        const h = stamp.height * scale;

        ctx.strokeStyle = withAlpha(palette.fgSubtle, shown * 0.55);
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
        ctx.setLineDash([]);

        ctx.font = `400 8px ${palette.mono}`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = withAlpha(palette.fgSubtle, shown * 0.9);
        ctx.fillText(stamp.text, x + w / 2, y + h / 2 + 0.5);
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
      };

      CHAIN_FLOWS.forEach((flow, i) => strokeFlow(flow, phase[FLOW_PHASES[i]]));
      CHAIN_BOXES.forEach((box, i) => drawBox(box, phase[BOX_PHASES[i]]));

      for (const stamp of CHAIN_STAMPS) {
        const owner = BOX_PHASES[CHAIN_BOXES.findIndex((b) => b.key === stamp.forKey)];
        drawStamp(stamp, phase[owner]);
      }

      // The tally, last: the boxes describe the descent, none of them says what
      // the chain itself is.
      if (phase.reply > 0.2) {
        ctx.font = `400 9px ${palette.mono}`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        ctx.fillStyle = withAlpha(palette.fgSubtle, clamp01((phase.reply - 0.2) / 0.6) * 0.9);
        ctx.fillText(CHAIN_SUMMARY, px(0), HEIGHT - 3);
      }
    };

    const frame = (now: number): void => {
      raf = requestAnimationFrame(frame);
      const target = progress();
      const dt = first ? 16 : Math.min(now - lastTime, 64);
      lastTime = now;
      if (first) {
        eased = target;
        first = false;
      } else {
        eased += (target - eased) * (1 - Math.exp(-dt / TAU));
      }
      draw(eased);
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

    resize();
    // Reduced motion gets the finished diagram rather than an empty card: the
    // building is the decoration, the chain is the content.
    if (motion.matches) draw(1);
    else start();

    const visibility = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) start();
        else stop();
      },
      { rootMargin: '20% 0px' }
    );
    visibility.observe(canvas);

    const onVisibilityChange = (): void => {
      if (document.hidden) stop();
      else if (!motion.matches) start();
    };

    const onMotionChange = (): void => {
      if (motion.matches) {
        stop();
        draw(1);
      } else {
        first = true;
        start();
      }
    };

    const onResize = (): void => {
      resize();
      if (motion.matches) draw(1);
    };

    window.addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibilityChange);
    motion.addEventListener('change', onMotionChange);

    return () => {
      stop();
      visibility.disconnect();
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      motion.removeEventListener('change', onMotionChange);
    };
  }, []);

  return (
    <figure className="landing-note p-5">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
          Provider chain
        </span>
        <span className="flex-1 border-t border-dashed border-line" />
      </div>

      {/* Sized in CSS rather than by the attribute, so the fixed drawing surface
          scales down instead of overflowing the reading column on a phone —
          below `xl` this figure reflows out of the rail and into the prose. */}
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="A request enters the chain, two providers decline and are left on cooldown, and the third answers"
        className="w-full"
        style={{ maxWidth: WIDTH, aspectRatio: `${WIDTH} / ${HEIGHT}` }}
      />

      <figcaption className="mt-3 border-t border-dashed border-line pt-3 font-mono text-2xs text-fg-subtle">
        {LLM.presets} presets · {LLM.adapters.length} adapters
      </figcaption>
    </figure>
  );
}
