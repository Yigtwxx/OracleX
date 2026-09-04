import type { Palette } from '@/lib/chart-palette';

/**
 * The chart options every panel on this board shares.
 *
 * Pulled out because seven panels repeating a grid, an axis style and a tooltip
 * shell is seven chances for one of them to drift a pixel and read as a
 * different chart language. Colours arrive resolved: ECharts paints to canvas,
 * so a `var(--token)` string reaches it as an unparseable colour and paints
 * nothing at all.
 */
export function axisBase(palette: Palette) {
  return {
    axisLine: { lineStyle: { color: palette['--border'] } },
    axisTick: { show: false },
    axisLabel: { color: palette['--fg-subtle'], fontSize: 10 },
    splitLine: { lineStyle: { color: palette['--border'], type: 'dashed' as const } },
  };
}

export function gridBase() {
  return { left: 56, right: 52, top: 16, bottom: 28, containLabel: false };
}

export function tooltipBase(palette: Palette) {
  return {
    trigger: 'axis' as const,
    backgroundColor: palette['--surface-2'],
    borderColor: palette['--border-strong'],
    textStyle: { color: palette['--fg'], fontSize: 11 },
  };
}

export function legendBase(palette: Palette) {
  return {
    textStyle: { color: palette['--fg-muted'], fontSize: 10 },
    itemHeight: 8,
    itemWidth: 12,
    top: 0,
  };
}

/** A series colour wheel that stays distinguishable in both themes. */
export function seriesColors(palette: Palette): string[] {
  return [
    palette['--oi-total'],
    palette['--oi-venue-1'],
    palette['--oi-price'],
    palette['--oi-venue-3'],
    palette['--oi-venue-2'],
  ];
}
