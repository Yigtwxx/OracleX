import { CandleSeries } from './candle-series';
import { NOTE_ANCHORS } from './note-anchors';
import { withAlpha } from './palette';
import type { Layout, RenderFrame } from './renderer';
import { SceneState } from './scene';
import { StageKey } from './stages';

/**
 * A copy panel's box in viewport CSS pixels.
 *
 * The canvas is `position: fixed` over the whole viewport, so a panel's
 * `getBoundingClientRect()` is already in canvas space — no conversion, and no
 * need for the panels and the scene to share a coordinate system beyond the one
 * the browser hands both of them.
 */
export interface NoteRect {
  readonly key: StageKey;
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;
}

/** Which way the bar a panel is wired to closed. */
export interface NoteTone {
  readonly key: StageKey;
  readonly tone: 'up' | 'down';
}

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

interface Point {
  readonly x: number;
  readonly y: number;
}

interface Attach extends Point {
  /** 'side' is a left/right edge, approached horizontally; 'face' is top/bottom. */
  readonly edge: 'side' | 'face';
}

/**
 * Where on the panel's outline the wire lands: whichever edge faces the bar,
 * inset from the corners so it never meets one.
 */
function attachPoint(rect: NoteRect, x: number, y: number): Attach {
  const inset = 24;
  const clampY = Math.max(rect.top + inset, Math.min(y, rect.bottom - inset));
  if (x <= rect.left) return { x: rect.left, y: clampY, edge: 'side' };
  if (x >= rect.right) return { x: rect.right, y: clampY, edge: 'side' };
  const edgeX = Math.max(rect.left + inset, Math.min(x, rect.right - inset));
  return { x: edgeX, y: y <= rect.top ? rect.top : rect.bottom, edge: 'face' };
}

/**
 * The wire's route: right angles only, no diagonals.
 *
 * It leaves the bar vertically — a horizontal first segment would run straight
 * through the bars either side of it — turns once onto a lane clear of the
 * tape, and turns again to come into the panel square. Orthogonal routing is
 * also what every charting tool draws its callouts with, so it reads as part of
 * the chart rather than as a line laid over it.
 */
function routeOf(from: Point, to: Attach, lift: number): Point[] {
  const laneY = from.y + lift;
  if (to.edge === 'face') return [from, { x: from.x, y: laneY }, { x: to.x, y: laneY }, to];

  // Stop short of the panel, drop to the attach height, then come in flat.
  const knee = to.x + (from.x >= to.x ? 44 : -44);
  return [from, { x: from.x, y: laneY }, { x: knee, y: laneY }, { x: knee, y: to.y }, to];
}

/** Strokes the first `fraction` of a polyline, so the wire grows from the bar. */
function strokeRoute(
  ctx: CanvasRenderingContext2D,
  route: readonly Point[],
  fraction: number
): void {
  const lengths = route.slice(1).map((p, i) => Math.hypot(p.x - route[i].x, p.y - route[i].y));
  const total = lengths.reduce((sum, l) => sum + l, 0);
  if (total <= 0) return;

  let budget = total * fraction;
  ctx.beginPath();
  ctx.moveTo(route[0].x, route[0].y);
  for (let i = 0; i < lengths.length; i += 1) {
    const length = lengths[i];
    const next = route[i + 1];
    if (budget >= length) {
      ctx.lineTo(next.x, next.y);
      budget -= length;
      continue;
    }
    const t = length > 0 ? budget / length : 0;
    ctx.lineTo(route[i].x + (next.x - route[i].x) * t, route[i].y + (next.y - route[i].y) * t);
    break;
  }
  ctx.stroke();
}

/**
 * The bar each panel is wired to, once resolved.
 *
 * Resolved once, when the wire starts appearing, and then held. Re-deriving it
 * per frame from the visible window made the wire hop from bar to bar as the
 * tape panned, which is the one thing a pointer must never do — it stops
 * reading as "this bar" and starts reading as a glitch.
 *
 * Keyed by slot count as well so a resize, which changes the whole layout,
 * picks a bar that suits the new one.
 */
const resolved = new Map<StageKey, { readonly index: number; readonly slots: number }>();

/**
 * Picks the bar for a panel: the far side of the plot from the panel itself.
 * A bar next to the panel gives a wire that is over before the eye finds it.
 */
function pickBar(
  pick: number,
  rect: NoteRect,
  layout: Layout,
  state: SceneState,
  printed: number
): number | undefined {
  const last = Math.min(printed, state.windowFrom + state.slots) - 1;
  if (last < state.windowFrom) return undefined;

  const panelOnLeft = (rect.left + rect.right) / 2 < layout.plotRight / 2;
  const frac = panelOnLeft ? 0.7 + pick * 0.22 : 0.06 + pick * 0.22;
  const index = state.windowFrom + Math.round((layout.plotRight * frac) / layout.slotWidth - 0.5);
  return Math.max(state.windowFrom, Math.min(index, last));
}

/**
 * Draws the dotted wire from each panel's bar to the panel itself.
 *
 * See `routeOf` for the shape: right angles only, leaving the bar vertically
 * and arriving at the panel square.
 */
export function drawNoteLeaders(
  frame: RenderFrame,
  state: SceneState,
  layout: Layout,
  series: CandleSeries,
  rects: readonly NoteRect[]
): NoteTone[] {
  const tones: NoteTone[] = [];
  if (state.printedCount <= 0) return tones;

  const { ctx, palette } = frame;
  const printed = Math.floor(state.printedCount);
  const windowTo = state.windowFrom + state.slots;

  ctx.save();
  for (const anchor of NOTE_ANCHORS) {
    const rect = rects.find((r) => r.key === anchor.key);
    const reveal = rect
      ? clamp01((state.progress - anchor.from) / Math.max(anchor.to - anchor.from, 1e-6))
      : 0;

    // Scrolled back above the panel: forget the bar so a second pass through
    // re-picks one that suits wherever the tape is by then.
    if (!rect || reveal <= 0.01) {
      resolved.delete(anchor.key);
      continue;
    }

    let entry = resolved.get(anchor.key);
    if (!entry || entry.slots !== state.slots) {
      const index = pickBar(anchor.pick, rect, layout, state, printed);
      if (index === undefined) continue;
      entry = { index, slots: state.slots };
      resolved.set(anchor.key, entry);
    }

    // The tape has panned past its bar. The wire is dropped rather than
    // re-pointed — by then the panel is on its way off screen anyway.
    const { index } = entry;
    if (index < state.windowFrom || index >= windowTo || index >= printed) continue;

    const candle = series.candles[index];
    const x = layout.xOf(index);
    if (x < 0 || x > layout.plotRight) continue;

    // Reported back so the panel can carry a trace of the bar it belongs to.
    // The wire says which bar; the tint says what that bar did.
    tones.push({ key: anchor.key, tone: candle.c >= candle.o ? 'up' : 'down' });

    const high = anchor.side === 'high';
    const y = layout.yOf(high ? candle.h : candle.l) + (high ? -7 : 7);
    const end = attachPoint(rect, x, y);
    const route = routeOf({ x, y }, end, high ? -74 : 74);

    const alpha = frame.alpha * reveal;
    ctx.setLineDash([2, 5]);
    ctx.lineWidth = 1.5;
    ctx.lineCap = 'butt';
    // Mitred, not rounded: the corners are the point of the shape.
    ctx.lineJoin = 'miter';
    ctx.strokeStyle = withAlpha(palette.accent, alpha * 0.95);
    strokeRoute(ctx, route, reveal);

    // The tick on the bar itself. Solid and drawn last, so the origin of the
    // wire is never ambiguous.
    ctx.setLineDash([]);
    ctx.fillStyle = withAlpha(palette.accent, alpha);
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
  return tones;
}
