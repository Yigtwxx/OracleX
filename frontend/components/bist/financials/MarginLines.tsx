'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';

import type { BistFinancials } from '@/lib/bist-api';
import { marginSeries } from '@/lib/bist-financials';
import { FALLBACK, type Palette, readPalette } from '@/lib/chart-palette';

import { axisBase, gridBase, legendBase, seriesColors, tooltipBase } from './chart-base';

/**
 * Trailing margins, which have no price frame.
 *
 * Numerator and denominator are in the same period's lira, so inflation divides
 * out exactly and this panel is identical under either toggle position. That is
 * worth stating rather than leaving the reader to notice a chart that ignored
 * their click — the panel's legend says it, and this is the only chart on the
 * board that does not take the `basis` prop at all.
 */
export default function MarginLines({ payload }: { payload: BistFinancials }) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const series = marginSeries(payload);
  const periods = payload.ratios.map((row) => row.period);
  const colors = seriesColors(palette);

  const option = {
    grid: gridBase(),
    tooltip: {
      ...tooltipBase(palette),
      valueFormatter: (value: number | null) =>
        value == null ? '—' : `%${(value * 100).toFixed(1)}`,
    },
    legend: legendBase(palette),
    xAxis: { type: 'category', data: periods, ...axisBase(palette) },
    yAxis: {
      type: 'value',
      ...axisBase(palette),
      axisLabel: {
        color: palette['--fg-subtle'],
        fontSize: 10,
        formatter: (value: number) => `%${(value * 100).toFixed(0)}`,
      },
    },
    series: series.map((one, index) => ({
      name: one.label,
      type: 'line',
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
      connectNulls: false,
      lineStyle: { width: 1.5, color: colors[index] },
      itemStyle: { color: colors[index] },
      data: one.points.map((point) => point.value),
    })),
  };

  return <ReactECharts option={option} style={{ height: 240 }} notMerge lazyUpdate />;
}
