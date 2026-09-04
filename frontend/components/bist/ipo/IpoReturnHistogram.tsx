'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';

import type { Ipo } from '@/lib/bist-api';
import { type IpoBasis, returnBuckets } from '@/lib/bist-ipo';
import { FALLBACK, type Palette, readPalette } from '@/lib/chart-palette';

/**
 * The board's only aggregate: did buying these offerings work.
 *
 * Buckets are fixed rather than derived, so two windows can be compared. Bars
 * are coloured by the sign of the bucket they cover, because that is the one
 * question the panel answers and a single hue would make the reader count.
 */
export default function IpoReturnHistogram({ rows, basis }: { rows: Ipo[]; basis: IpoBasis }) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const buckets = returnBuckets(rows, basis);

  const option = {
    grid: { left: 36, right: 12, top: 16, bottom: 56, containLabel: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: palette['--surface-2'],
      borderColor: palette['--border-strong'],
      textStyle: { color: palette['--fg'], fontSize: 11 },
      valueFormatter: (value: number) => `${value} arz`,
    },
    xAxis: {
      type: 'category',
      data: buckets.map((bucket) => bucket.label),
      axisLine: { lineStyle: { color: palette['--border'] } },
      axisTick: { show: false },
      axisLabel: { color: palette['--fg-subtle'], fontSize: 9, rotate: 40 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { lineStyle: { color: palette['--border'] } },
      axisTick: { show: false },
      axisLabel: { color: palette['--fg-subtle'], fontSize: 10 },
      splitLine: { lineStyle: { color: palette['--border'], type: 'dashed' } },
    },
    series: [
      {
        type: 'bar',
        data: buckets.map((bucket, index) => ({
          value: bucket.count,
          // Index 3 is the first bucket whose whole range is above zero.
          itemStyle: { color: index >= 3 ? palette['--up'] : palette['--down'] },
        })),
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 260 }} notMerge lazyUpdate />;
}
