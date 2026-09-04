'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';

import type { BistFinancials } from '@/lib/bist-api';
import { type Basis, quarterSeries, unitFor } from '@/lib/bist-financials';
import { FALLBACK, type Palette, readPalette } from '@/lib/chart-palette';

import { axisBase, gridBase, legendBase, seriesColors, tooltipBase } from './chart-base';

/**
 * Leverage and, more usefully, its maturity.
 *
 * The stack splits total debt into what is due inside a year and what is not,
 * because in a 40%-rate economy the short-term share is the reading that
 * decides whether a company refinances at a survivable price. Cash rides on the
 * same axis so the net position is visible without arithmetic.
 */
export default function DebtStack({ payload, basis }: { payload: BistFinancials; basis: Basis }) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const [total, short, cash] = quarterSeries(payload, basis, [
    'total_debt',
    'short_term_debt',
    'cash',
  ]);
  const periods = total?.points.map((point) => point.period) ?? [];
  const unit = unitFor(total?.points.map((point) => point.value) ?? []);
  const colors = seriesColors(palette);

  const shortValues = short?.points.map((point) => point.value) ?? [];
  const longValues =
    total?.points.map((point, index) => {
      const shortValue = shortValues[index];
      if (point.value == null) return null;
      // Long-term debt is not a reported line; it is the remainder. With no
      // short-term figure the split is unknown, so the whole bar is withheld
      // rather than drawn as if it were all long-dated.
      return shortValue == null ? null : point.value - shortValue;
    }) ?? [];

  const option = {
    grid: gridBase(),
    tooltip: tooltipBase(palette),
    legend: legendBase(palette),
    xAxis: { type: 'category', data: periods, ...axisBase(palette) },
    yAxis: [
      {
        type: 'value',
        name: unit.label,
        nameTextStyle: { color: palette['--fg-subtle'], fontSize: 10, align: 'right' },
        ...axisBase(palette),
      },
      { type: 'value', name: 'x', ...axisBase(palette), splitLine: { show: false } },
    ],
    series: [
      {
        name: 'Kısa vadeli borç',
        type: 'bar',
        stack: 'debt',
        itemStyle: { color: palette['--down'] },
        data: shortValues.map((value) => (value == null ? null : value / unit.divisor)),
      },
      {
        name: 'Uzun vadeli borç',
        type: 'bar',
        stack: 'debt',
        itemStyle: { color: colors[3] },
        data: longValues.map((value) => (value == null ? null : value / unit.divisor)),
      },
      {
        name: 'Nakit',
        type: 'line',
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 1.5, color: palette['--up'] },
        itemStyle: { color: palette['--up'] },
        data: cash?.points.map((point) =>
          point.value == null ? null : point.value / unit.divisor
        ),
      },
      {
        name: 'Net borç / FAVÖK',
        type: 'line',
        yAxisIndex: 1,
        symbol: 'circle',
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { width: 1.5, type: 'dashed', color: palette['--warn'] },
        itemStyle: { color: palette['--warn'] },
        data: payload.ratios.map((row) => row.net_debt_ebitda),
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 260 }} notMerge lazyUpdate />;
}
