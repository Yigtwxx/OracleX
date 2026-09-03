import { CandleSeries } from './candle-series';
import { RenderPalette, withAlpha } from './palette';
import { drawNoteLeaders, type NoteRect, type NoteTone } from './renderer-leaders';
import { renderMarks } from './renderer-marks';
import { SceneState } from './scene';
import { windowFor } from './stages';

export interface RenderFrame {
  readonly ctx: CanvasRenderingContext2D;
  /** CSS pixels. The context already carries the device-pixel-ratio transform. */
  readonly width: number;
  readonly height: number;
  readonly palette: RenderPalette;
  /**
   * Global multiplier. 1 on the animated path; lower on the reduced-motion path,
   * where the finished chart sits behind the hero copy and must not fight it.
   */
  readonly alpha: number;
}

/** Maps candle indices and prices onto the canvas. */
export interface Layout {
  readonly plotTop: number;
  readonly plotBottom: number;
  readonly volumeTop: number;
  readonly volumeBottom: number;
  readonly plotRight: number;
  readonly slotWidth: number;
  readonly bodyWidth: number;
  xOf(index: number): number;
  yOf(price: number): number;
}

const GUTTER_RIGHT = 78;
const TOP_FRAC = 0.13;
const PRICE_BOTTOM_FRAC = 0.775;
const VOLUME_BOTTOM_FRAC = 0.9;
/**
 * Rows of grid squares down the price plot, and price labels up the axis.
 *
 * Two constants rather than one because they want different answers. The grid
 * is background — bigger cells, fewer of them — while the axis is information,
 * and three prices on a chart this tall is not enough to read a level off.
 *
 * `PRICE_TICKS` is a multiple of `GRID_ROWS`, so every grid line still lands on
 * a labelled price. Break that and the ruling stops agreeing with the numbers
 * beside it, which is worse than having no ruling at all.
 */
const GRID_ROWS = 2;
const PRICE_TICKS = 4;
const SESSION_EVERY = 24;

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

export function buildLayout(frame: RenderFrame, state: SceneState): Layout {
  const plotTop = frame.height * TOP_FRAC;
  const plotBottom = frame.height * PRICE_BOTTOM_FRAC;
  const volumeTop = plotBottom + 18;
  const volumeBottom = frame.height * VOLUME_BOTTOM_FRAC;
  const plotRight = frame.width - GUTTER_RIGHT;
  const slotWidth = plotRight / state.slots;

  // Sub-slot offset: once the window is full the newest candle is fractional, so
  // shifting by the unfinished remainder is what turns a per-candle jump into a
  // continuous pan.
  const panning = state.printedCount > state.slots;
  const shift = panning ? Math.ceil(state.printedCount) - state.printedCount : 0;
  const span = Math.max(state.priceMax - state.priceMin, 1e-6);

  return {
    plotTop,
    plotBottom,
    volumeTop,
    volumeBottom,
    plotRight,
    slotWidth,
    bodyWidth: Math.max(slotWidth * 0.62, 1),
    xOf: (index) => (index - state.windowFrom + 0.5 + shift) * slotWidth,
    yOf: (price) => plotBottom - ((price - state.priceMin) / span) * (plotBottom - plotTop),
  };
}

function drawGrid(frame: RenderFrame, state: SceneState, layout: Layout): void {
  const { ctx, palette } = frame;
  const alpha = state.gridAlpha * frame.alpha;
  if (alpha <= 0.002) return;

  // Square, not ruled. The vertical pitch is taken from the horizontal one
  // rather than chosen, which is the whole point: a fixed number of columns
  // would stretch into rectangles at any width but the intended one, and the
  // background would stop reading as paper the chart is drawn on.
  const cell = (layout.plotBottom - layout.plotTop) / GRID_ROWS;

  ctx.save();
  ctx.lineWidth = 1;
  ctx.strokeStyle = withAlpha(palette.line, alpha * 0.85);
  ctx.beginPath();
  for (let row = 0; row <= GRID_ROWS; row += 1) {
    const y = Math.round(layout.plotTop + cell * row);
    ctx.moveTo(0, y + 0.5);
    ctx.lineTo(layout.plotRight, y + 0.5);
  }
  // Anchored to the left edge rather than to the candles: this is the paper,
  // and paper does not slide when the tape pans across it. The session marks
  // below are the layer that moves.
  for (let x = 0; x <= layout.plotRight; x += cell) {
    const px = Math.round(x);
    ctx.moveTo(px + 0.5, layout.plotTop);
    ctx.lineTo(px + 0.5, layout.plotBottom);
  }
  ctx.stroke();

  // Session boundaries. Anchored to absolute candle indices so they slide with
  // the pan rather than strobing in place. Dimmer than it was now that there is
  // a static grid underneath — two vertical layers at the same weight read as
  // one confused one.
  ctx.strokeStyle = withAlpha(palette.line, alpha * 0.42);
  ctx.setLineDash([2, 6]);
  ctx.beginPath();
  const firstSession = Math.ceil(state.windowFrom / SESSION_EVERY) * SESSION_EVERY;
  for (let i = firstSession; i < state.windowFrom + state.slots; i += SESSION_EVERY) {
    const x = Math.round(layout.xOf(i)) + 0.5;
    if (x < 0 || x > layout.plotRight) continue;
    ctx.moveTo(x, layout.plotTop);
    ctx.lineTo(x, layout.volumeBottom);
  }
  ctx.stroke();
  ctx.restore();
}

/**
 * Draws one candle, extruding from its open in its own direction — reds grow
 * downward, greens upward — so the print reads as the market moving rather than
 * as a bar being revealed.
 */
function drawCandle(
  frame: RenderFrame,
  layout: Layout,
  candle: CandleSeries['candles'][number],
  x: number,
  t: number,
  emphasis: number
): void {
  const { ctx, palette } = frame;
  const rising = candle.c >= candle.o;
  const color = rising ? palette.up : palette.down;
  const alpha = Math.min(1, t * 3) * frame.alpha;
  if (alpha <= 0.002) return;

  const growing = candle.o + (candle.c - candle.o) * t;
  const top = layout.yOf(Math.max(candle.o, growing));
  const bottom = layout.yOf(Math.min(candle.o, growing));

  // Wicks shoot out only after the body has mostly formed. Drawing them in
  // lockstep makes every candle look like it is being scaled up from nothing.
  const wickT = clamp01((t - 0.6) / 0.4);
  const finalTop = Math.max(candle.o, candle.c);
  const finalBottom = Math.min(candle.o, candle.c);
  const highY = layout.yOf(Math.max(candle.o, growing) + (candle.h - finalTop) * wickT);
  const lowY = layout.yOf(Math.min(candle.o, growing) - (finalBottom - candle.l) * wickT);

  const half = layout.bodyWidth / 2;
  const bodyTop = Math.round(top);
  const bodyHeight = Math.max(Math.round(Math.max(bottom - top, 1)), 1);
  const bodyBottom = bodyTop + bodyHeight;

  // The wick is drawn as two segments that stop at the body rather than as one
  // line running behind it. A single line showed through as a thin stripe down
  // the middle of every candle, which reads as a rendering artefact.
  const cx = Math.round(x) + 0.5;
  ctx.strokeStyle = withAlpha(color, alpha * (0.7 + emphasis * 0.3));
  ctx.lineWidth = 1;
  ctx.beginPath();
  if (highY < bodyTop) {
    ctx.moveTo(cx, highY);
    ctx.lineTo(cx, bodyTop);
  }
  if (lowY > bodyBottom) {
    ctx.moveTo(cx, bodyBottom);
    ctx.lineTo(cx, lowY);
  }
  ctx.stroke();

  // Bodies stay fully opaque: the transparency that once softened them let the
  // grid and the wick bleed through, which cost the candles their weight.
  ctx.fillStyle = withAlpha(color, alpha);
  ctx.fillRect(Math.round(x - half), bodyTop, Math.round(half * 2), bodyHeight);

  if (emphasis > 0.01 && layout.bodyWidth > 3) {
    ctx.strokeStyle = withAlpha(color, alpha * emphasis);
    ctx.strokeRect(
      Math.round(x - half) + 0.5,
      bodyTop + 0.5,
      Math.round(half * 2) - 1,
      bodyHeight - 1
    );
  }
}

function drawVolume(
  frame: RenderFrame,
  layout: Layout,
  candle: CandleSeries['candles'][number],
  maxVolume: number,
  x: number,
  t: number
): void {
  const { ctx, palette } = frame;
  const alpha = Math.min(1, t * 3) * frame.alpha * 0.34;
  if (alpha <= 0.002) return;

  const height = (candle.v / maxVolume) * (layout.volumeBottom - layout.volumeTop) * t;
  ctx.fillStyle = withAlpha(candle.c >= candle.o ? palette.up : palette.down, alpha);
  ctx.fillRect(
    Math.round(x - layout.bodyWidth / 2),
    Math.round(layout.volumeBottom - height),
    Math.round(layout.bodyWidth),
    Math.max(Math.round(height), 1)
  );
}

function formatPrice(price: number): string {
  return price.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

/**
 * The right-hand price scale slides in during the market-data panel — the point
 * in the page where the copy starts talking about live prices.
 */
function drawPriceScale(frame: RenderFrame, state: SceneState, layout: Layout): void {
  const live = windowFor('live');
  const reveal = clamp01((state.progress - live.from) / ((live.to - live.from) * 0.45));
  if (reveal <= 0.01) return;

  const { ctx, palette } = frame;
  const alpha = reveal * frame.alpha;
  const slide = (1 - reveal) * 20;

  ctx.save();
  ctx.font = `500 11px ${palette.mono}`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = withAlpha(palette.fgSubtle, alpha * 0.9);
  for (let tick = 0; tick <= PRICE_TICKS; tick += 1) {
    const ratio = tick / PRICE_TICKS;
    const y = layout.plotTop + (layout.plotBottom - layout.plotTop) * ratio;
    const price = state.priceMax - (state.priceMax - state.priceMin) * ratio;
    ctx.fillText(formatPrice(price), layout.plotRight + 10 + slide, y);
  }
  ctx.restore();
}

/** The dashed last-price line and its tag — the "this is live" read. */
function drawLastPrice(
  frame: RenderFrame,
  state: SceneState,
  layout: Layout,
  series: CandleSeries
): void {
  const index = Math.min(Math.floor(state.printedCount), series.candles.length - 1);
  if (index < 0) return;
  const partial = state.printedCount - Math.floor(state.printedCount);
  const candle = series.candles[index];
  const price = candle.o + (candle.c - candle.o) * (partial > 0 ? partial : 1);
  const y = Math.round(layout.yOf(price)) + 0.5;
  const rising = candle.c >= candle.o;

  const { ctx, palette } = frame;
  const color = rising ? palette.up : palette.down;
  ctx.save();
  ctx.setLineDash([3, 4]);
  ctx.lineWidth = 1;
  ctx.strokeStyle = withAlpha(color, 0.45 * frame.alpha);
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(layout.plotRight, y);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.font = `600 11px ${palette.mono}`;
  ctx.textBaseline = 'middle';
  const label = formatPrice(price);
  const textWidth = ctx.measureText(label).width;
  ctx.fillStyle = withAlpha(color, 0.9 * frame.alpha);
  ctx.fillRect(layout.plotRight + 4, y - 8, textWidth + 12, 16);
  ctx.fillStyle = withAlpha(palette.surface, frame.alpha);
  ctx.fillText(label, layout.plotRight + 10, y + 0.5);
  ctx.restore();
}

/** The tape itself: every printed candle and its volume, and nothing else. */
function drawBars(
  frame: RenderFrame,
  state: SceneState,
  layout: Layout,
  series: CandleSeries
): void {
  const complete = Math.floor(state.printedCount);
  const lastVisible = Math.min(complete, state.windowFrom + state.slots);

  for (let i = state.windowFrom; i < lastVisible; i += 1) {
    const x = layout.xOf(i);
    if (x < -layout.slotWidth || x > layout.plotRight + layout.slotWidth) continue;
    // The two newest bars sit brighter, so the eye tracks the head of the tape.
    const emphasis = clamp01((i - (complete - 2)) / 2);
    drawCandle(frame, layout, series.candles[i], x, 1, emphasis);
    drawVolume(frame, layout, series.candles[i], series.maxVolume, x, 1);
  }

  const partial = state.printedCount - complete;
  if (partial > 0 && complete < series.candles.length) {
    const x = layout.xOf(complete);
    drawCandle(frame, layout, series.candles[complete], x, partial, 1);
    drawVolume(frame, layout, series.candles[complete], series.maxVolume, x, partial);
  }
}

export function renderScene(
  frame: RenderFrame,
  state: SceneState,
  series: CandleSeries,
  /** Copy-panel boxes in viewport pixels, for the leaders that tie them to bars. */
  notes: readonly NoteRect[] = []
  /** Returns which bar each panel ended up wired to, so the panel can tint. */
): NoteTone[] {
  const { ctx } = frame;
  ctx.clearRect(0, 0, frame.width, frame.height);
  // The whole "clean hero" rule, enforced once more at the last possible moment.
  if (state.gridAlpha <= 0 && state.printedCount <= 0) return [];

  const layout = buildLayout(frame, state);
  drawGrid(frame, state, layout);
  if (state.printedCount <= 0) return [];

  drawBars(frame, state, layout, series);

  renderMarks(frame, state, layout, series);
  const tones = drawNoteLeaders(frame, state, layout, series, notes);
  drawPriceScale(frame, state, layout);
  drawLastPrice(frame, state, layout, series);
  return tones;
}

/**
 * The board with nothing said about it: bars, volume, and the grid.
 *
 * The documentation pages sit a column of prose on top of this, and the full
 * scene is not a backdrop — it is a chart with eight pattern annotations, a
 * price scale and a last-price tag, every one of which is a piece of type
 * competing with the paragraph over it. Turning the alpha down far enough to
 * fix that turned the tape down with it, so the annotations come off instead.
 *
 * Deliberately not a flag on `renderScene`. That function's contract is "draw
 * the scene the landing page is about", and a boolean that removes half of it
 * would make every future reader check which half they were getting.
 */
export function renderTape(frame: RenderFrame, state: SceneState, series: CandleSeries): void {
  const { ctx } = frame;
  ctx.clearRect(0, 0, frame.width, frame.height);
  if (state.gridAlpha <= 0 && state.printedCount <= 0) return;

  const layout = buildLayout(frame, state);
  drawGrid(frame, state, layout);
  if (state.printedCount <= 0) return;

  drawBars(frame, state, layout, series);
}
