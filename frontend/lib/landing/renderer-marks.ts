import { Mark } from './analysis-marks';
import { CandleSeries } from './candle-series';
import { withAlpha } from './palette';
import type { Layout, RenderFrame } from './renderer';
import { SceneState } from './scene';

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

function priceAt(series: CandleSeries, index: number, anchor: 'high' | 'low'): number {
  const candle = series.candles[Math.max(0, Math.min(index, series.candles.length - 1))];
  return anchor === 'high' ? candle.h : candle.l;
}

function toneColor(frame: RenderFrame, tone: 'up' | 'down' | 'accent' | 'muted'): string {
  const { palette } = frame;
  if (tone === 'up') return palette.up;
  if (tone === 'down') return palette.down;
  if (tone === 'accent') return palette.accent;
  return palette.fgMuted;
}

/** A bordered annotation box. Title in mono, optional detail line beneath it. */
function drawLabel(
  frame: RenderFrame,
  x: number,
  y: number,
  title: string,
  detail: string | undefined,
  color: string,
  alpha: number,
  align: 'left' | 'right' = 'left'
): void {
  const { ctx, palette } = frame;
  ctx.save();
  ctx.font = `600 11px ${palette.mono}`;
  const titleWidth = ctx.measureText(title).width;
  ctx.font = `400 10px ${palette.mono}`;
  const detailWidth = detail ? ctx.measureText(detail).width : 0;

  const padX = 8;
  const width = Math.max(titleWidth, detailWidth) + padX * 2;
  const height = detail ? 34 : 22;
  const left = align === 'left' ? x : x - width;
  const top = y - height / 2;

  ctx.fillStyle = withAlpha(palette.surface, alpha * 0.96);
  ctx.fillRect(left, top, width, height);
  ctx.strokeStyle = withAlpha(color, alpha);
  ctx.lineWidth = 1;
  ctx.strokeRect(left + 0.5, top + 0.5, width - 1, height - 1);
  // The spine that makes the box read as an annotation rather than a tooltip.
  // Same device as `.landing-note` in globals.css, so the copy panels and the
  // marks on the tape are visibly the same kind of object.
  ctx.fillStyle = withAlpha(color, alpha * 0.85);
  ctx.fillRect(left, top, 2, height);

  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.font = `600 11px ${palette.mono}`;
  ctx.fillStyle = withAlpha(color, alpha);
  ctx.fillText(title, left + padX, detail ? top + 12 : top + height / 2);
  if (detail) {
    ctx.font = `400 10px ${palette.mono}`;
    ctx.fillStyle = withAlpha(palette.fgMuted, alpha * 0.95);
    ctx.fillText(detail, left + padX, top + 25);
  }
  ctx.restore();
}

function drawMovingAverage(
  frame: RenderFrame,
  state: SceneState,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'ma' }>,
  reveal: number
): void {
  const complete = Math.floor(state.printedCount);
  const start = Math.max(state.windowFrom, mark.period - 1);
  const end = Math.min(complete, state.windowFrom + state.slots);
  if (end - start < 2) return;

  // Only `reveal` of the path is stroked, so the line reads as being drawn.
  const drawTo = start + Math.floor((end - start) * reveal);
  if (drawTo - start < 2) return;

  const { ctx } = frame;
  const color = toneColor(frame, mark.tone);
  ctx.save();
  ctx.lineWidth = mark.tone === 'accent' ? 1.5 : 1;
  ctx.strokeStyle = withAlpha(color, (mark.tone === 'accent' ? 0.75 : 0.5) * frame.alpha);
  ctx.beginPath();
  for (let i = start; i < drawTo; i += 1) {
    let sum = 0;
    for (let k = 0; k < mark.period; k += 1) sum += series.candles[i - k].c;
    const y = layout.yOf(sum / mark.period);
    const x = layout.xOf(i);
    if (i === start) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawLevel(
  frame: RenderFrame,
  state: SceneState,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'level' }>,
  reveal: number
): void {
  const price = priceAt(series, mark.index, mark.anchor);
  const y = Math.round(layout.yOf(price)) + 0.5;
  const startX = Math.max(layout.xOf(mark.index), 0);
  const endX = startX + (layout.plotRight - startX) * reveal;

  const { ctx } = frame;
  const color = toneColor(frame, mark.tone);
  ctx.save();
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = withAlpha(color, 0.8 * frame.alpha);
  ctx.beginPath();
  ctx.moveTo(startX, y);
  ctx.lineTo(endX, y);
  ctx.stroke();
  ctx.restore();

  if (reveal > 0.6) {
    const labelAlpha = clamp01((reveal - 0.6) / 0.4) * frame.alpha;
    // Left end of the line, lifted clear of it. The right edge belongs to the
    // last-price tag, and a level that happens to sit near spot would collide
    // with it — which is exactly when a support label matters most.
    const labelX = Math.max(startX + 6, 12);
    drawLabel(
      frame,
      labelX,
      y - 16,
      `${mark.label} · ${Math.round(price).toLocaleString('en-US')}`,
      undefined,
      color,
      labelAlpha,
      'left'
    );
  }
}

function drawTrendline(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'trendline' }>,
  reveal: number
): void {
  const x1 = layout.xOf(mark.from);
  const y1 = layout.yOf(priceAt(series, mark.from, mark.anchor));
  const x2 = layout.xOf(mark.to);
  const y2 = layout.yOf(priceAt(series, mark.to, mark.anchor));

  // Extended past the second anchor: a trendline that stops at its last touch
  // is a line segment, not a projection.
  const extend = 1.7;
  const ex = x1 + (x2 - x1) * extend;
  const ey = y1 + (y2 - y1) * extend;
  const tipX = x1 + (ex - x1) * reveal;
  const tipY = y1 + (ey - y1) * reveal;

  const { ctx, palette } = frame;
  ctx.save();
  ctx.lineWidth = 1.25;
  ctx.strokeStyle = withAlpha(palette.accent, 0.85 * frame.alpha);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(tipX, tipY);
  ctx.stroke();

  for (const index of [mark.from, mark.to]) {
    ctx.fillStyle = withAlpha(palette.accent, 0.85 * frame.alpha);
    ctx.beginPath();
    ctx.arc(
      layout.xOf(index),
      layout.yOf(priceAt(series, index, mark.anchor)),
      2.5,
      0,
      Math.PI * 2
    );
    ctx.fill();
  }
  ctx.restore();

  if (reveal > 0.75) {
    drawLabel(
      frame,
      tipX + 8,
      tipY,
      mark.label,
      undefined,
      palette.accent,
      clamp01((reveal - 0.75) / 0.25) * frame.alpha
    );
  }
}

function drawZone(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'zone' }>,
  reveal: number
): void {
  let top = -Infinity;
  let bottom = Infinity;
  for (let i = mark.from; i <= mark.to; i += 1) {
    top = Math.max(top, series.candles[i].h);
    bottom = Math.min(bottom, series.candles[i].l);
  }

  const x1 = layout.xOf(mark.from) - layout.slotWidth / 2;
  const x2 = layout.xOf(mark.to) + layout.slotWidth / 2;
  const yTop = layout.yOf(top);
  const yBottom = layout.yOf(bottom);
  const width = (x2 - x1) * reveal;

  const { ctx } = frame;
  const color = toneColor(frame, mark.tone);
  ctx.save();
  ctx.fillStyle = withAlpha(color, 0.14 * frame.alpha);
  ctx.fillRect(x1, yTop, width, yBottom - yTop);
  ctx.strokeStyle = withAlpha(color, 0.62 * frame.alpha);
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.strokeRect(x1 + 0.5, yTop + 0.5, Math.max(width - 1, 0), yBottom - yTop - 1);
  ctx.setLineDash([]);

  if (reveal > 0.5) {
    ctx.font = `600 10px ${frame.palette.mono}`;
    ctx.textBaseline = 'bottom';
    ctx.textAlign = 'left';
    ctx.fillStyle = withAlpha(color, clamp01((reveal - 0.5) / 0.5) * frame.alpha);
    ctx.fillText(mark.label.toUpperCase(), x1 + 6, yTop - 5);
  }
  ctx.restore();
}

function drawCallout(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'callout' }>,
  reveal: number
): void {
  const x = layout.xOf(mark.index);
  const y = layout.yOf(priceAt(series, mark.index, mark.anchor));
  const direction = mark.anchor === 'high' ? -1 : 1;
  const leaderLength = 54;
  const grow = clamp01(reveal / 0.6);
  const tipX = x + 26 * grow;
  // Kept inside the price plot: the marks layer is clipped at the volume band,
  // and a leader that runs past it leaves its label box sliced in half.
  const tipY = Math.min(
    Math.max(y + direction * leaderLength * grow, layout.plotTop + 26),
    layout.volumeTop - 40
  );

  const { ctx, palette } = frame;
  ctx.save();
  ctx.lineWidth = 1;
  ctx.strokeStyle = withAlpha(palette.fgMuted, 0.55 * frame.alpha);
  ctx.beginPath();
  ctx.moveTo(x, y + direction * 4);
  ctx.lineTo(tipX, tipY);
  ctx.stroke();

  ctx.fillStyle = withAlpha(palette.fg, 0.8 * frame.alpha);
  ctx.beginPath();
  ctx.arc(x, y + direction * 4, 2, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  if (reveal > 0.55) {
    const alpha = clamp01((reveal - 0.55) / 0.45) * frame.alpha;
    // Flip the box to the left when it would run off the plot.
    const align = tipX > layout.plotRight - 190 ? 'right' : 'left';
    drawLabel(
      frame,
      align === 'left' ? tipX + 6 : tipX - 6,
      tipY + direction * 12,
      mark.title,
      mark.detail,
      palette.fg,
      alpha,
      align
    );
  }
}

function drawMeasure(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'measure' }>,
  reveal: number
): void {
  const low = priceAt(series, mark.from, 'low');
  const high = priceAt(series, mark.to, 'high');
  const x = Math.min(layout.xOf(mark.to) + layout.slotWidth * 4, layout.plotRight - 24);
  const yLow = layout.yOf(low);
  const yHigh = layout.yOf(high);
  const tip = yLow + (yHigh - yLow) * reveal;

  const { ctx, palette } = frame;
  ctx.save();
  ctx.lineWidth = 1;
  // Dashed and dim: the riser spans most of the plot height, and a solid line
  // that long stops reading as an annotation and starts cutting the chart in two.
  ctx.strokeStyle = withAlpha(palette.up, 0.42 * frame.alpha);
  ctx.setLineDash([3, 5]);
  ctx.beginPath();
  ctx.moveTo(x, yLow);
  ctx.lineTo(x, tip);
  ctx.stroke();

  ctx.setLineDash([]);
  ctx.strokeStyle = withAlpha(palette.up, 0.75 * frame.alpha);
  ctx.beginPath();
  ctx.moveTo(x - 5, yLow);
  ctx.lineTo(x + 5, yLow);
  ctx.moveTo(x - 5, tip);
  ctx.lineTo(x + 5, tip);
  ctx.stroke();
  ctx.restore();

  if (reveal > 0.7) {
    const gain = ((high - low) / low) * 100;
    drawLabel(
      frame,
      x + 8,
      (yLow + yHigh) / 2,
      `+${gain.toFixed(1)}%`,
      undefined,
      palette.up,
      clamp01((reveal - 0.7) / 0.3) * frame.alpha
    );
  }
}

function drawSweep(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'sweep' }>,
  reveal: number
): void {
  const x = layout.xOf(mark.index);
  const y = layout.yOf(priceAt(series, mark.index, 'low')) + 12;
  const size = 4 * reveal;

  const { ctx, palette } = frame;
  ctx.save();
  ctx.lineWidth = 1.4;
  ctx.strokeStyle = withAlpha(palette.down, 0.8 * frame.alpha);
  ctx.beginPath();
  ctx.moveTo(x - size, y - size);
  ctx.lineTo(x + size, y + size);
  ctx.moveTo(x + size, y - size);
  ctx.lineTo(x - size, y + size);
  ctx.stroke();

  if (reveal > 0.6) {
    ctx.font = `500 10px ${palette.mono}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = withAlpha(palette.down, clamp01((reveal - 0.6) / 0.4) * frame.alpha);
    ctx.fillText(mark.label, x, y + 8);
  }
  ctx.restore();
}

/** Index of the extreme bar in a closed range. Ties keep the earlier bar. */
function extremeIndex(
  series: CandleSeries,
  from: number,
  to: number,
  pick: 'high' | 'low'
): number {
  let best = from;
  for (let i = from; i <= to; i += 1) {
    const better =
      pick === 'high'
        ? series.candles[i].h > series.candles[best].h
        : series.candles[i].l < series.candles[best].l;
    if (better) best = i;
  }
  return best;
}

interface Point {
  readonly x: number;
  readonly y: number;
}

/**
 * Strokes the first `t` of a polyline by arc length.
 *
 * Revealing by length rather than by vertex is what keeps the drawing speed
 * even: the left shoulder of a head-and-shoulders is a much shorter run than
 * the climb to the head, and a per-vertex reveal would race through one and
 * crawl through the other.
 */
function strokePolyline(ctx: CanvasRenderingContext2D, points: readonly Point[], t: number): void {
  if (points.length < 2 || t <= 0) return;

  const lengths: number[] = [];
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    const d = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
    lengths.push(d);
    total += d;
  }
  if (total <= 0) return;

  let budget = total * clamp01(t);
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i += 1) {
    const d = lengths[i - 1];
    if (budget >= d) {
      ctx.lineTo(points[i].x, points[i].y);
      budget -= d;
      continue;
    }
    const k = d === 0 ? 0 : budget / d;
    ctx.lineTo(
      points[i - 1].x + (points[i].x - points[i - 1].x) * k,
      points[i - 1].y + (points[i].y - points[i - 1].y) * k
    );
    break;
  }
  ctx.stroke();
}

/**
 * Head and shoulders, or its inverse.
 *
 * Drawn as the pattern is actually read: first the three pivots joined into the
 * silhouette, then the neckline underneath them, then the name. The neckline is
 * found here rather than passed in — it runs through the two counter-pivots
 * between the shoulders and the head, which is a fact about the bars.
 */
function drawHeadShoulders(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'headShoulders' }>,
  reveal: number
): void {
  const pointAt = (index: number, anchor: 'high' | 'low'): Point => ({
    x: layout.xOf(index),
    y: layout.yOf(priceAt(series, index, anchor)),
  });

  const shoulders = [mark.left, mark.head, mark.right].map((i) => pointAt(i, mark.anchor));

  const neckAnchor = mark.anchor === 'high' ? 'low' : 'high';
  const neckLeft = pointAt(extremeIndex(series, mark.left, mark.head, neckAnchor), neckAnchor);
  const neckRight = pointAt(extremeIndex(series, mark.head, mark.right, neckAnchor), neckAnchor);

  const { ctx } = frame;
  const color = toneColor(frame, mark.tone);

  ctx.save();
  ctx.lineWidth = 1.25;
  ctx.strokeStyle = withAlpha(color, 0.8 * frame.alpha);
  strokePolyline(ctx, shoulders, clamp01(reveal / 0.62));

  // The neckline starts once the silhouette is most of the way drawn, and runs
  // past the right shoulder — the break is the part of the pattern that matters
  // and it happens to the right of everything drawn so far.
  const neckReveal = clamp01((reveal - 0.45) / 0.45);
  const extend = 1.55;
  const neckTip = {
    x: neckLeft.x + (neckRight.x - neckLeft.x) * extend,
    y: neckLeft.y + (neckRight.y - neckLeft.y) * extend,
  };
  if (neckReveal > 0) {
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = withAlpha(color, 0.6 * frame.alpha);
    strokePolyline(ctx, [neckLeft, neckTip], neckReveal);
    ctx.setLineDash([]);
  }

  const dotReveal = clamp01(reveal / 0.62);
  ctx.fillStyle = withAlpha(color, 0.9 * frame.alpha);
  shoulders.forEach((point, i) => {
    // Each dot lands as the line reaches it, so the pivots are marked rather
    // than pre-announced.
    if (dotReveal < i / shoulders.length) return;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 2.5, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();

  if (reveal > 0.78) {
    const alpha = clamp01((reveal - 0.78) / 0.22) * frame.alpha;
    // Under the middle of the neckline, not on the head and not on the
    // neckline's extended tip. The head is the busiest bar on the chart — the
    // blow-off callout and the sweep both point at it — and the tip follows the
    // neckline's slope, which on a rising market climbs straight back into that
    // same crowd. The middle of the neckline is the one part of the pattern
    // with nothing else drawn on it.
    const neckMid = {
      x: (neckLeft.x + neckRight.x) / 2,
      y: (neckLeft.y + neckRight.y) / 2,
    };
    const lift = mark.anchor === 'high' ? 22 : -22;
    const align = neckMid.x > layout.plotRight - 200 ? 'right' : 'left';
    drawLabel(
      frame,
      align === 'left' ? neckMid.x + 8 : neckMid.x - 8,
      Math.min(Math.max(neckMid.y + lift, layout.plotTop + 16), layout.volumeTop - 24),
      mark.label,
      undefined,
      color,
      alpha,
      align
    );
  }
}

/**
 * A wedge: the two trendlines that bound a range, drawn from its own pivots.
 *
 * Each side is fitted through the extreme of the first half and the extreme of
 * the second, which is how a wedge is drawn by hand and, unlike a regression,
 * guarantees both lines actually touch bars.
 */
function drawWedge(
  frame: RenderFrame,
  layout: Layout,
  series: CandleSeries,
  mark: Extract<Mark, { kind: 'wedge' }>,
  reveal: number
): void {
  const mid = Math.floor((mark.from + mark.to) / 2);
  if (mid <= mark.from || mid >= mark.to) return;

  const { ctx } = frame;
  const color = toneColor(frame, mark.tone);
  // Past the last bar, so the two lines are seen converging rather than merely
  // sloping. This is the whole reason the shape is called a wedge.
  const endX = layout.xOf(mark.to + 5);

  ctx.save();
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = withAlpha(color, 0.7 * frame.alpha);
  ctx.setLineDash([5, 4]);

  const apex: Point[] = [];
  for (const anchor of ['high', 'low'] as const) {
    const a = extremeIndex(series, mark.from, mid, anchor);
    const b = extremeIndex(series, mid + 1, mark.to, anchor);
    const ax = layout.xOf(a);
    const ay = layout.yOf(priceAt(series, a, anchor));
    const bx = layout.xOf(b);
    const by = layout.yOf(priceAt(series, b, anchor));
    if (bx === ax) continue;
    const slope = (by - ay) / (bx - ax);
    const end = { x: endX, y: ay + slope * (endX - ax) };
    apex.push(end);
    strokePolyline(ctx, [{ x: ax, y: ay }, end], reveal);
  }
  ctx.setLineDash([]);
  ctx.restore();

  if (reveal > 0.8 && apex.length === 2) {
    drawLabel(
      frame,
      Math.min(endX, layout.plotRight - 12),
      (apex[0].y + apex[1].y) / 2,
      mark.label,
      undefined,
      color,
      clamp01((reveal - 0.8) / 0.2) * frame.alpha,
      'right'
    );
  }
}

/**
 * True when a mark no longer has anything on screen to point at.
 *
 * Once the tape pans past a callout's candle, its leader line points off the
 * left edge and the label box is clipped in half — worse than not drawing it.
 * Levels are exempt: a horizontal line is still meaningful after its anchor has
 * scrolled away, which is the entire point of a level. It is dropped instead
 * when its price leaves the visible domain.
 */
function isStale(mark: Mark, state: SceneState, series: CandleSeries): boolean {
  switch (mark.kind) {
    case 'callout':
    case 'sweep':
      return mark.index < state.windowFrom;
    // Half a pattern is not a pattern: once the left shoulder or the start of
    // the wedge has panned off, what is left on screen is two unexplained lines.
    case 'headShoulders':
      return mark.left < state.windowFrom;
    case 'wedge':
      return mark.from < state.windowFrom;
    case 'level': {
      const price = priceAt(series, mark.index, mark.anchor);
      return price < state.priceMin || price > state.priceMax;
    }
    default:
      return false;
  }
}

/**
 * The analysis layer. Clipped to the price plot — left of the price gutter and
 * above the volume band — and drawn strictly after the candles so nothing is
 * painted over.
 */
export function renderMarks(
  frame: RenderFrame,
  state: SceneState,
  layout: Layout,
  series: CandleSeries
): void {
  const { ctx } = frame;
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 0, layout.plotRight, layout.volumeTop - 6);
  ctx.clip();

  for (const { mark, reveal } of state.marks) {
    if (reveal <= 0.005 || isStale(mark, state, series)) continue;
    switch (mark.kind) {
      case 'ma':
        drawMovingAverage(frame, state, layout, series, mark, reveal);
        break;
      case 'level':
        drawLevel(frame, state, layout, series, mark, reveal);
        break;
      case 'trendline':
        drawTrendline(frame, layout, series, mark, reveal);
        break;
      case 'zone':
        drawZone(frame, layout, series, mark, reveal);
        break;
      case 'callout':
        drawCallout(frame, layout, series, mark, reveal);
        break;
      case 'measure':
        drawMeasure(frame, layout, series, mark, reveal);
        break;
      case 'sweep':
        drawSweep(frame, layout, series, mark, reveal);
        break;
      case 'headShoulders':
        drawHeadShoulders(frame, layout, series, mark, reveal);
        break;
      case 'wedge':
        drawWedge(frame, layout, series, mark, reveal);
        break;
    }
  }
  ctx.restore();
}
