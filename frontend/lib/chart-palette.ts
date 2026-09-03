/**
 * Design tokens as literal colours, for charts that render to canvas.
 *
 * ECharts' canvas renderer hands colour strings straight to the 2D context,
 * which silently ignores CSS custom properties — `var(--token)` in a chart
 * option renders as nothing at all. Every chart therefore has to resolve its
 * palette from the document after hydration rather than passing tokens through,
 * and needs a literal fallback for the server render that precedes it.
 */

/** Design tokens the charts need as literal colours. */
export const TOKENS = [
  '--fg',
  '--fg-muted',
  '--fg-subtle',
  '--surface',
  '--surface-2',
  '--border',
  '--border-strong',
  '--up',
  '--down',
  '--up-bg',
  '--down-bg',
  '--heat-seq-1',
  '--heat-seq-2',
  '--heat-seq-3',
  '--heat-seq-4',
  '--warn',
  '--oi-total',
  '--oi-venue-1',
  '--oi-venue-2',
  '--oi-venue-3',
  '--oi-price',
] as const;

export type Token = (typeof TOKENS)[number];
export type Palette = Record<Token, string>;

/** Values from globals.css, used until the document is available. */
export const FALLBACK: Palette = {
  '--fg': '#e8e8ea',
  '--fg-muted': '#9a9aa3',
  '--fg-subtle': '#6b6b74',
  '--surface': '#111114',
  '--surface-2': '#17171b',
  '--border': '#232328',
  '--border-strong': '#34343b',
  '--up': '#22c55e',
  '--down': '#ef4444',
  '--up-bg': 'rgba(34, 197, 94, 0.12)',
  '--down-bg': 'rgba(239, 68, 68, 0.12)',
  '--heat-seq-1': '#1f3b6e',
  '--heat-seq-2': '#285099',
  '--heat-seq-3': '#2f63c3',
  '--heat-seq-4': '#4788ff',
  '--warn': '#f59e0b',
  '--oi-total': '#5ac8fa',
  '--oi-venue-1': '#3ecf8e',
  '--oi-venue-2': '#4db6ac',
  '--oi-venue-3': '#8b7fe8',
  '--oi-price': '#e0a63d',
};

export function readPalette(): Palette {
  if (typeof window === 'undefined') return FALLBACK;
  const computed = getComputedStyle(document.documentElement);
  const palette = { ...FALLBACK };
  for (const token of TOKENS) {
    const value = computed.getPropertyValue(token).trim();
    if (value) palette[token] = value;
  }
  return palette;
}

/** `#rrggbb` → `[r, g, b]`. */
export function parseHex(hex: string): [number, number, number] {
  const clean = hex.replace('#', '');
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((c) => c + c)
          .join('')
      : clean;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

export function compactUsd(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}
