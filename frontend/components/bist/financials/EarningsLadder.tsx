'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';

import type { BistFinancials } from '@/lib/bist-api';
import { type Basis, FIELD_LABELS, quarterSeries, unitFor } from '@/lib/bist-financials';
import { FALLBACK, type Palette, readPalette } from '@/lib/chart-palette';

import { axisBase, gridBase, legendBase, seriesColors, tooltipBase } from './chart-base';

/**
 * The whole income statement per quarter, in one frame.
 *
 * Revenue is the bar and every profit line rides on top of it, because the
 * reading is proportional: what matters is not that net income rose but how
 * much of the bar it is. Two axes would break that — the lines would float free
 * of the bar they come out of — so everything shares one scale and one divisor.
 *
 * A provisional quarter is drawn at reduced opacity. It was restated with an
 * index that does not yet cover its own month, and a bar that says so is better
 * than a footnote nobody reads next to a bar that does not.
 */
export default function EarningsLadder({
  payload,
  basis,
  barField,
  lineFields,
}: {
  payload: BistFinancials;
  basis: Basis;
  barField: string;
  lineFields: string[];
}) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const series = quarterSeries(payload, basis, [barField, ...lineFields]);
  const periods = series[0]?.points.map((point) => point.period) ?? [];
  const unit = unitFor(series.flatMap((one) => one.points.map((point) => point.value)));
  const colors = seriesColors(palette);
  const provisional = new Set(payload.deflation.provisional_periods);

  const scaled = (index: number) =>
    series[index]?.points.map((point) =>
      point.value == null ? null : point.value / unit.divisor
    ) ?? [];

  const option = {
    grid: gridBase(),
    tooltip: {
      ...tooltipBase(palette),
      valueFormatter: (value: number | null) =>
        value == null ? '—' : `${value.toFixed(1)} ${unit.label}`,
    },
    legend: legendBase(palette),
    xAxis: { type: 'category', data: periods, ...axisBase(palette) },
    yAxis: {
      type: 'value',
      name: unit.label,
      nameTextStyle: { color: palette['--fg-subtle'], fontSize: 10, align: 'right' },
      ...axisBase(palette),
    },
    series: [
      {
        name: FIELD_LABELS[barField] ?? barField,
        type: 'bar',
        data: scaled(0).map((value, index) => ({
          value,
          itemStyle: provisional.has(periods[index])
            ? {
                color: colors[0],
                opacity: 0.55,
                borderColor: colors[0],
                borderType: 'dotted',
                borderWidth: 1,
              }
            : { color: colors[0] },
        })),
      },
      ...lineFields.map((field, index) => ({
        name: FIELD_LABELS[field] ?? field,
        type: 'line',
        smooth: false,
        symbol: 'circle',
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { width: 1.5, color: colors[index + 1] },
        itemStyle: { color: colors[index + 1] },
        data: scaled(index + 1),
      })),
    ],
  };

  return <ReactECharts option={option} style={{ height: 260 }} notMerge lazyUpdate />;
}
