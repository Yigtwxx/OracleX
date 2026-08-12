import { describe, it, expect } from 'vitest';

import { insetTile, squarify, type TreemapInput, type TreemapTile } from './treemap';

/** Roughly the market-cap distribution of a real top-25 board. */
const REALISTIC: TreemapInput[] = [
  { id: 'btc', value: 1.28e12 },
  { id: 'eth', value: 2.26e11 },
  { id: 'bnb', value: 7.86e10 },
  { id: 'xrp', value: 6.72e10 },
  { id: 'sol', value: 4.29e10 },
  { id: 'trx', value: 3.12e10 },
  { id: 'hype', value: 1.23e10 },
  { id: 'doge', value: 1.09e10 },
  { id: 'ada', value: 8.4e9 },
  { id: 'link', value: 7.1e9 },
  { id: 'xlm', value: 5.5e9 },
  { id: 'avax', value: 4.9e9 },
  { id: 'ltc', value: 4.2e9 },
  { id: 'dot', value: 3.8e9 },
  { id: 'uni', value: 3.1e9 },
  { id: 'atom', value: 2.4e9 },
  { id: 'near', value: 1.9e9 },
  { id: 'fil', value: 1.4e9 },
  { id: 'algo', value: 1.1e9 },
  { id: 'vet', value: 9e8 },
];

function area(tile: TreemapTile): number {
  return tile.w * tile.h;
}

function overlaps(a: TreemapTile, b: TreemapTile): boolean {
  const epsilon = 1e-6;
  return (
    a.x < b.x + b.w - epsilon &&
    b.x < a.x + a.w - epsilon &&
    a.y < b.y + b.h - epsilon &&
    b.y < a.y + a.h - epsilon
  );
}

describe('squarify', () => {
  it('fills the whole container', () => {
    const tiles = squarify(REALISTIC, 800, 500);
    const total = tiles.reduce((sum, tile) => sum + area(tile), 0);
    expect(total).toBeCloseTo(800 * 500, -1);
  });

  it('gives each tile an area proportional to its value', () => {
    const width = 800;
    const height = 500;
    const tiles = squarify(REALISTIC, width, height);
    const totalValue = REALISTIC.reduce((sum, item) => sum + item.value, 0);
    const byId = new Map(tiles.map((tile) => [tile.id, tile]));

    for (const item of REALISTIC) {
      const tile = byId.get(item.id);
      expect(tile, `${item.id} must be laid out`).toBeDefined();
      const areaShare = area(tile!) / (width * height);
      expect(areaShare).toBeCloseTo(item.value / totalValue, 6);
    }
  });

  it('keeps every tile inside the container', () => {
    const tiles = squarify(REALISTIC, 640, 400);
    for (const tile of tiles) {
      expect(tile.x).toBeGreaterThanOrEqual(-1e-6);
      expect(tile.y).toBeGreaterThanOrEqual(-1e-6);
      expect(tile.x + tile.w).toBeLessThanOrEqual(640 + 1e-6);
      expect(tile.y + tile.h).toBeLessThanOrEqual(400 + 1e-6);
    }
  });

  it('never overlaps two tiles', () => {
    const tiles = squarify(REALISTIC, 900, 600);
    for (let i = 0; i < tiles.length; i += 1) {
      for (let j = i + 1; j < tiles.length; j += 1) {
        expect(overlaps(tiles[i], tiles[j]), `${tiles[i].id} overlaps ${tiles[j].id}`).toBe(false);
      }
    }
  });

  it('keeps most tiles close to square', () => {
    // The whole point of squarifying: a slice-and-dice layout would leave the
    // smallest assets as unreadable one-pixel slivers.
    const tiles = squarify(REALISTIC, 900, 600);
    const ratios = tiles.map((tile) => Math.max(tile.w / tile.h, tile.h / tile.w));
    const acceptable = ratios.filter((ratio) => ratio < 5).length;
    expect(acceptable / ratios.length).toBeGreaterThanOrEqual(0.9);
  });

  it('orders tiles by descending value', () => {
    const tiles = squarify(REALISTIC, 800, 500);
    expect(tiles[0].id).toBe('btc');
    expect(area(tiles[0])).toBeGreaterThan(area(tiles[1]));
  });

  it('gives a single item the entire container', () => {
    // Compared with a tolerance on purpose: the layout stays in floating point
    // and rounds only at render, so `w` here is 300.00000000000006.
    const [tile] = squarify([{ id: 'only', value: 42 }], 300, 200);
    expect(tile.id).toBe('only');
    expect(tile.x).toBeCloseTo(0, 6);
    expect(tile.y).toBeCloseTo(0, 6);
    expect(tile.w).toBeCloseTo(300, 6);
    expect(tile.h).toBeCloseTo(200, 6);
  });

  it('returns nothing for an empty input', () => {
    expect(squarify([], 300, 200)).toEqual([]);
  });

  it('returns nothing when the container has no area', () => {
    expect(squarify(REALISTIC, 0, 200)).toEqual([]);
    expect(squarify(REALISTIC, 300, 0)).toEqual([]);
  });

  it('drops values that cannot occupy area', () => {
    const tiles = squarify(
      [
        { id: 'real', value: 100 },
        { id: 'zero', value: 0 },
        { id: 'negative', value: -5 },
        { id: 'nan', value: Number.NaN },
      ],
      200,
      200
    );
    expect(tiles.map((tile) => tile.id)).toEqual(['real']);
  });
});

describe('insetTile', () => {
  it('shrinks a tile symmetrically', () => {
    const tile = insetTile({ id: 'a', x: 10, y: 20, w: 100, h: 50 }, 4);
    expect(tile).toEqual({ id: 'a', x: 12, y: 22, w: 96, h: 46 });
  });

  it('never produces a negative size', () => {
    // Sub-gap tiles are real: the smallest asset on a crowded board can be
    // narrower than the gutter, and a negative width would break the layout.
    const tile = insetTile({ id: 'a', x: 0, y: 0, w: 2, h: 1 }, 6);
    expect(tile.w).toBe(0);
    expect(tile.h).toBe(0);
  });
});
