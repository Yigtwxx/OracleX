'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';

import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';

export interface ChartSeries {
  name: string;
  /** `[isoDate, value]` pairs, oldest first. */
  points: [string, number][];
  /** A resolved colour, or a `Palette` token the wrapper will look up. */
  color: string;
  /** Fill under the line. Off for a comparison overlay. */
  area?: boolean;
  /** Dashed, for a reference line such as an inflation-adjusted baseline. */
  dashed?: boolean;
}

interface BistChartProps {
  series: ChartSeries[];
  height?: number;
  /** Format a y value for the axis and the tooltip. */
  formatValue: (value: number) => string;
}

/**
 * A time series, drawn the way every other chart in this codebase is.
 *
 * The palette dance is not optional and not a style choice. ECharts renders to
 * canvas, and the 2D context takes colour strings literally — a `var(--token)`
 * in an option object paints nothing at all. So the palette is resolved from
 * the document *after* hydration, with `FALLBACK` covering the server render
 * that precedes it. `lib/chart-palette.ts` documents the constraint; every
 * chart in `components/charts/` does exactly this.
 *
 * `animation: false` and `renderer: 'canvas'` match the rest of the codebase:
 * these boards refetch on a timer, and an animated redraw every two minutes
 * reads as the page twitching rather than as data arriving.
 */
export default function BistChart({ series, height = 260, formatValue }: BistChartProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const option = useMemo(() => {
    const resolve = (colour: string) =>
      colour.startsWith('--') ? (palette[colour as keyof Palette] ?? colour) : colour;

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 8, right: 12, top: 24, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        valueFormatter: (value: number) => formatValue(value),
        axisPointer: { lineStyle: { color: palette['--border-strong'] } },
      },
      legend:
        series.length > 1
          ? {
              top: 0,
              right: 0,
              textStyle: { color: palette['--fg-muted'], fontSize: 11 },
              icon: 'roundRect',
              itemWidth: 8,
              itemHeight: 8,
            }
          : undefined,
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisLabel: { color: palette['--fg-subtle'], fontSize: 10, hideOverlap: true },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => formatValue(value),
        },
        splitLine: {
          lineStyle: { color: palette['--border'], type: 'dashed', opacity: 0.5 },
        },
      },
      series: series.map((line) => {
        const colour = resolve(line.color);
        return {
          name: line.name,
          type: 'line',
          showSymbol: false,
          smooth: false,
          lineStyle: { width: 1.6, color: colour, type: line.dashed ? 'dashed' : 'solid' },
          itemStyle: { color: colour },
          areaStyle: line.area
            ? {
                color: {
                  type: 'linear',
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: `${colour}33` },
                    { offset: 1, color: `${colour}00` },
                  ],
                },
              }
            : undefined,
          data: line.points.map(([day, value]) => [day, value]),
        };
      }),
    };
  }, [series, palette, formatValue]);

  const hasData = series.some((line) => line.points.length > 0);
  if (!hasData) {
    return (
      <div style={{ height }} className="flex items-center justify-center text-sm text-fg-subtle">
        Grafik için yeterli veri yok.
      </div>
    );
  }

  return (
    <ReactECharts
      option={option}
      notMerge
      opts={{ renderer: 'canvas' }}
      style={{ height, width: '100%' }}
    />
  );
}
