import { describe, it, expect } from 'vitest';

import {
  bucketFor,
  PRICE_SCALE,
  SCORE_SCALE,
  TURNOVER_SCALE,
  UNKNOWN_BUCKET,
  VOLUME_SCALE,
  type HeatBucket,
} from './heatmap-scale';

const SCALES: [string, readonly HeatBucket[]][] = [
  ['price', PRICE_SCALE],
  ['volume', VOLUME_SCALE],
  ['turnover', TURNOVER_SCALE],
  ['score', SCORE_SCALE],
];

/** A value comfortably inside `bucket`, given the bucket above it. */
function sampleValue(bucket: HeatBucket, above: HeatBucket | undefined): number {
  if (bucket.min === Number.NEGATIVE_INFINITY) {
    // The catch-all: pick something well below the next boundary up.
    return above ? above.min - 1000 : -1000;
  }
  if (!above) return bucket.min + 1000;
  return (bucket.min + above.min) / 2;
}

describe.each(SCALES)('%s scale', (_name, scale) => {
  it('renders a legend that agrees with the colour it paints', () => {
    // The defect this pins: the legend was hand-written beside the colour
    // function and drifted from it, showing a swatch the price scale never
    // produced while omitting two buckets it did.
    scale.forEach((bucket, index) => {
      const value = sampleValue(bucket, scale[index - 1]);
      expect(bucketFor(value, scale), `${value} should land in "${bucket.label}"`).toBe(bucket);
    });
  });

  it('is ordered from the highest bound down', () => {
    const bounds = scale.map((bucket) => bucket.min);
    expect(bounds).toEqual([...bounds].sort((a, b) => b - a));
  });

  it('ends in a catch-all so every real number matches', () => {
    expect(scale[scale.length - 1].min).toBe(Number.NEGATIVE_INFINITY);
  });

  it('reports an unknown value as unknown, not as the lowest bucket', () => {
    expect(bucketFor(undefined, scale)).toBe(UNKNOWN_BUCKET);
  });

  it('treats a non-finite value as unknown', () => {
    expect(bucketFor(Number.NaN, scale)).toBe(UNKNOWN_BUCKET);
    expect(bucketFor(Number.POSITIVE_INFINITY, scale)).toBe(UNKNOWN_BUCKET);
  });

  it('never paints an unknown the same way as a measured value', () => {
    // "No data" and "lowest bucket" used to share a flat swatch, which is what
    // made the Volume tab look broken rather than empty.
    for (const bucket of scale) {
      expect(bucket.className).not.toBe(UNKNOWN_BUCKET.className);
    }
  });

  it('uses a distinct label for every bucket', () => {
    const labels = scale.map((bucket) => bucket.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it('pairs every background with the ink that stays readable on it', () => {
    // Declared together so they cannot drift: the ramps span a real lightness
    // range, so the brightest stop needs dark text while the rest need light.
    for (const bucket of scale) {
      const inks = ['text-fg', 'text-bg'].filter((ink) =>
        bucket.className.split(' ').includes(ink)
      );
      expect(inks, `"${bucket.label}" must declare exactly one ink`).toHaveLength(1);
    }
  });

  it('gives the brightest stop dark ink and the rest light ink', () => {
    const [brightest, ...rest] = scale;
    expect(brightest.className).toContain('text-bg');
    for (const bucket of rest) {
      if (bucket.className.includes('-4')) continue; // the other ramp's top stop
      expect(bucket.className).toContain('text-fg');
    }
  });
});

describe('price scale boundaries', () => {
  it('treats exactly zero as the first gain bucket', () => {
    expect(bucketFor(0, PRICE_SCALE).className).toContain('bg-heat-up-1');
  });

  it('treats a hair below zero as a loss', () => {
    expect(bucketFor(-0.01, PRICE_SCALE).className).toContain('bg-heat-down-1');
  });

  it('is symmetric in how many steps each direction gets', () => {
    // Asymmetry here is a distortion of the data, not just of the styling.
    const ups = PRICE_SCALE.filter((bucket) => bucket.className.includes('heat-up')).length;
    const downs = PRICE_SCALE.filter((bucket) => bucket.className.includes('heat-down')).length;
    expect(ups).toBe(downs);
  });

  it('puts a large loss in the strongest down bucket', () => {
    expect(bucketFor(-42, PRICE_SCALE).className).toContain('bg-heat-down-4');
  });
});

describe('unknown bucket', () => {
  it('carries a non-colour cue', () => {
    // Colour alone excludes anyone who cannot separate the darkest ramp stop
    // from the surface behind it.
    expect(UNKNOWN_BUCKET.className).toContain('dashed');
  });
});
