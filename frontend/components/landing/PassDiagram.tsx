'use client';

import { useEffect, useRef } from 'react';
import { readPalette, withAlpha } from '@/lib/landing/palette';
import {
  DRAFT_REVISED,
  FLOW_BACK,
  FLOW_IN,
  FLOW_LABELS,
  FLOW_OUT,
  PASS_BOXES,
  PASS_SUMMARY,
  PASS_VIEW,
  phasesAt,
  type PassBox,
  type Point,
} from '@/lib/landing/passes';

/** CSS size of the drawing surface. The card's padding sits outside it. */
const WIDTH = 500;
const HEIGHT = 286;
/** Time constant for the exponential approach, in milliseconds. */
const TAU = 190;

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * The report pipeline, building itself as the stage scrolls past.
 *
 * Its own canvas rather than a region of the page-wide scene: that one is a
 * market, this is a process, and putting a process diagram on the market's
 * surface would make it look like something the market did.
 *
 * Progress comes from this element's own position in the viewport rather than
 * from the page's scroll schedule, so the card is self-contained — it can move
 * to another stage without `stages.ts` needing to know it exists.
 */
export default function PassDiagram() {
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

    /**
     * 0 while the card is still climbing the lower half of the viewport, 1 once
     * it has settled around the middle. Finished well before it leaves the top:
     * a diagram that only completes on its way off screen is one nobody sees
     * completed.
     */
    const progress = (): number => {
      const box = canvas.getBoundingClientRect();
      const vh = window.innerHeight;
      return clamp01((vh * 0.86 - box.top) / (vh * 0.5));
    };

    const draw = (p: number): void => {
      const scale = Math.min(WIDTH / PASS_VIEW.width, HEIGHT / PASS_VIEW.height);
      const originX = (WIDTH - PASS_VIEW.width * scale) / 2;
      const originY = (HEIGHT - PASS_VIEW.height * scale) / 2;
      // Everything is converted to pixels rather than drawn under a canvas
      // transform, so the type stays on whole pixels and the hairlines stay
      // hairlines at any card size.
      const px = (x: number): number => originX + x * scale;
      const py = (y: number): number => originY + y * scale;

      const phase = phasesAt(p);
      ctx.clearRect(0, 0, WIDTH, HEIGHT);
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';

      const strokeFlow = (points: readonly Point[], t: number, color: string): void => {
        if (t <= 0) return;
        const pts = points.map((point) => ({ x: px(point.x), y: py(point.y) }));
        const lengths: number[] = [];
        let total = 0;
        for (let i = 1; i < pts.length; i += 1) {
          const d = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
          lengths.push(d);
          total += d;
        }

        let budget = total * t;
        let tip = pts[0];
        ctx.strokeStyle = withAlpha(color, 0.7);
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length; i += 1) {
          const d = lengths[i - 1];
          if (budget >= d) {
            ctx.lineTo(pts[i].x, pts[i].y);
            tip = pts[i];
            budget -= d;
            continue;
          }
          const k = d === 0 ? 0 : budget / d;
          tip = {
            x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * k,
            y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * k,
          };
          ctx.lineTo(tip.x, tip.y);
          break;
        }
        ctx.stroke();
        ctx.setLineDash([]);

        // The head only appears once the line has arrived. A head that travels
        // with the tip reads as a cursor rather than as a direction.
        if (t < 0.98) return;
        const last = pts[pts.length - 1];
        const prev = pts[pts.length - 2];
        const angle = Math.atan2(last.y - prev.y, last.x - prev.x);
        ctx.fillStyle = withAlpha(color, 0.85);
        ctx.beginPath();
        ctx.moveTo(last.x, last.y);
        ctx.lineTo(last.x - 6 * Math.cos(angle - 0.42), last.y - 6 * Math.sin(angle - 0.42));
        ctx.lineTo(last.x - 6 * Math.cos(angle + 0.42), last.y - 6 * Math.sin(angle + 0.42));
        ctx.closePath();
        ctx.fill();
      };

      const drawBox = (box: PassBox, alpha: number, detail: string, tone: string): void => {
        if (alpha <= 0) return;
        const x = px(box.x);
        const y = py(box.y);
        const w = box.width * scale;
        const h = box.height * scale;

        ctx.fillStyle = withAlpha(palette.surface, alpha * 0.92);
        ctx.fillRect(x, y, w, h);
        ctx.strokeStyle = withAlpha(tone, alpha * 0.8);
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
        // The same spine the annotation boxes on the tape use, so the diagram
        // is visibly the same family of object as the marks on the chart.
        ctx.fillStyle = withAlpha(tone, alpha * 0.85);
        ctx.fillRect(x, y, 2, h);

        ctx.textBaseline = 'alphabetic';
        ctx.textAlign = 'left';
        ctx.font = `600 11px ${palette.mono}`;
        ctx.fillStyle = withAlpha(palette.fg, alpha);
        ctx.fillText(box.title, x + 10, y + 17);

        ctx.font = `400 10px ${palette.mono}`;
        ctx.fillStyle = withAlpha(tone, alpha * 0.9);
        ctx.fillText(detail, x + 10, y + 30);

        // The rows the box is actually made of. They arrive one at a time on
        // the box's own reveal, so a four-source panel does not appear all at
        // once while the arrow into it is still being drawn.
        ctx.font = `400 9px ${palette.mono}`;
        box.lines.forEach((line, i) => {
          const rowAlpha = clamp01((alpha - 0.35 - i * 0.14) / 0.3);
          if (rowAlpha <= 0) return;
          ctx.fillStyle = withAlpha(palette.fgSubtle, rowAlpha * 0.95);
          ctx.fillText(line, x + 10, y + 45 + i * 12);
        });
      };

      const drawFlowLabel = (
        label: { readonly text: string; readonly at: Point },
        alpha: number,
        color: string
      ): void => {
        const shown = clamp01((alpha - 0.55) / 0.45);
        if (shown <= 0) return;
        ctx.font = `400 9px ${palette.mono}`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        ctx.fillStyle = withAlpha(color, shown * 0.85);
        ctx.fillText(label.text, px(label.at.x), py(label.at.y));
      };

      strokeFlow(FLOW_IN, phase.flowIn, palette.fgMuted);
      strokeFlow(FLOW_OUT, phase.flowOut, palette.fgMuted);
      strokeFlow(FLOW_BACK, phase.flowBack, palette.down);

      drawFlowLabel(FLOW_LABELS.out, phase.flowOut, palette.fgSubtle);
      drawFlowLabel(FLOW_LABELS.back, phase.flowBack, palette.down);

      const [evidence, draft, review] = PASS_BOXES;
      drawBox(evidence, phase.evidence, evidence.detail, palette.accent);
      drawBox(
        draft,
        phase.draft,
        phase.revised > 0.5 ? DRAFT_REVISED : draft.detail,
        phase.revised > 0.5 ? palette.up : palette.accent
      );
      drawBox(
        review,
        phase.review,
        review.detail,
        phase.review > 0.6 ? palette.down : palette.accent
      );

      // The tally, last. It is the only line that can say the loop closed —
      // every box above it describes a step, none of them describes the result.
      if (phase.revised > 0.2) {
        ctx.font = `400 10px ${palette.mono}`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        ctx.fillStyle = withAlpha(palette.fgSubtle, clamp01((phase.revised - 0.2) / 0.6) * 0.9);
        ctx.fillText(PASS_SUMMARY, px(1), HEIGHT - 3);
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
    // building is the decoration, the pipeline is the content.
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
    <div className="landing-note p-5">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
          Three passes per report
        </span>
        <span className="flex-1 border-t border-dashed border-line" />
      </div>

      <canvas
        ref={canvasRef}
        role="img"
        aria-label="Evidence feeds a draft, a review pass flags a claim, and the draft is rewritten"
        style={{ width: WIDTH, height: HEIGHT }}
      />
    </div>
  );
}
