/**
 * Squarified treemap layout (Bruls, Huizing & van Wijk, 2000).
 *
 * Pure geometry, no DOM and no React — which is what makes it testable, and
 * what lets the caller render each tile as a real focusable element rather than
 * a shape inside a canvas.
 *
 * The board it replaced sized tiles by their index in the current sort order,
 * so on the Developer tab the three largest tiles were the three busiest
 * repositories. Area is the channel that reads as "how much this matters"; here
 * it is bound to one value and the caller states which.
 */

export interface TreemapInput {
  id: string;
  /** Non-positive values are dropped: they have no area to occupy. */
  value: number;
}

export interface TreemapTile {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Worst (largest) aspect ratio in a row of areas laid along `side`.
 *
 * `sum` is the row's total area; the row is drawn `sum / side` deep, so each
 * item's ratio is that depth against its own width. Lower is squarer.
 */
function worstRatio(areas: number[], side: number, sum: number): number {
  if (sum <= 0 || side <= 0) return Infinity;
  const depth = sum / side;
  let worst = 0;
  for (const area of areas) {
    const width = area / depth;
    const ratio = width > 0 ? Math.max(depth / width, width / depth) : Infinity;
    if (ratio > worst) worst = ratio;
  }
  return worst;
}

/** Place one finished row along the short side of `rect`, and shrink `rect`. */
function placeRow(areas: number[], ids: string[], rect: Rect, tiles: TreemapTile[]): void {
  const sum = areas.reduce((total, area) => total + area, 0);
  if (sum <= 0) return;

  const horizontal = rect.w >= rect.h;
  const side = horizontal ? rect.h : rect.w;
  const depth = sum / side;

  let offset = 0;
  for (let i = 0; i < areas.length; i += 1) {
    const extent = areas[i] / depth;
    tiles.push(
      horizontal
        ? { id: ids[i], x: rect.x, y: rect.y + offset, w: depth, h: extent }
        : { id: ids[i], x: rect.x + offset, y: rect.y, w: extent, h: depth }
    );
    offset += extent;
  }

  if (horizontal) {
    rect.x += depth;
    rect.w -= depth;
  } else {
    rect.y += depth;
    rect.h -= depth;
  }
}

/**
 * Lay `items` out in a `width` × `height` rectangle, area proportional to value.
 *
 * Returns tiles in the input's descending-value order. Coordinates stay in
 * floating point: gaps between tiles belong at render time as an inset, because
 * subtracting them inside the recursion accumulates error and leaves the ragged
 * holes the CSS-grid version had.
 */
export function squarify(items: TreemapInput[], width: number, height: number): TreemapTile[] {
  if (width <= 0 || height <= 0) return [];

  const usable = items
    .filter((item) => Number.isFinite(item.value) && item.value > 0)
    .sort((a, b) => b.value - a.value);
  if (usable.length === 0) return [];

  const total = usable.reduce((sum, item) => sum + item.value, 0);
  const scale = (width * height) / total;

  const rect: Rect = { x: 0, y: 0, w: width, h: height };
  const tiles: TreemapTile[] = [];

  let rowAreas: number[] = [];
  let rowIds: string[] = [];
  let rowSum = 0;

  for (const item of usable) {
    const area = item.value * scale;
    const side = Math.min(rect.w, rect.h);

    // Keep growing the current row while doing so makes its worst tile squarer.
    // The moment it would get worse, the row is as good as it will be — close
    // it and start the next one against the remaining rectangle.
    const currentWorst = rowAreas.length ? worstRatio(rowAreas, side, rowSum) : Infinity;
    const nextWorst = worstRatio([...rowAreas, area], side, rowSum + area);

    if (rowAreas.length && nextWorst > currentWorst) {
      placeRow(rowAreas, rowIds, rect, tiles);
      rowAreas = [];
      rowIds = [];
      rowSum = 0;
    }

    rowAreas.push(area);
    rowIds.push(item.id);
    rowSum += area;
  }

  if (rowAreas.length) placeRow(rowAreas, rowIds, rect, tiles);

  return tiles;
}

/**
 * Shrink a tile by `gap`, keeping it centred.
 *
 * Applied at render rather than inside the layout so the gutters never eat into
 * the area that encodes the value, and never leave a sliver of a tile behind.
 */
export function insetTile(tile: TreemapTile, gap: number): TreemapTile {
  const half = gap / 2;
  return {
    id: tile.id,
    x: tile.x + half,
    y: tile.y + half,
    w: Math.max(0, tile.w - gap),
    h: Math.max(0, tile.h - gap),
  };
}
