'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';

import type { BistFinancials } from '@/lib/bist-api';
import { type Basis, quarterSeries, unitFor } from '@/lib/bist-financials';
import { FALLBACK, type Palette, readPalette } from '@/lib/chart-palette';

import { axisBase, gridBase, legendBase, seriesColors, tooltipBase } from './chart-base';

/**
 * Balance-sheet scale, and the return earned on it.
 *
 * The only panel every chart of accounts can fill. That is why it exists in
 * this shape: an insurer reports three lines and two of them are here, so the
 * board still has something to say about a company whose statements are thin
 * rather than degrading into a page of stated absences.
 */
export default function BalanceLines({
  payload,
  basis,
}: {
  payload: BistFinancials;
  basis: Basis;
}) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const [equity, assets] = quarterSeries(payload, basis, ['equity', 'total_assets']);
  const periods = equity?.points.map((point) => point.period) ?? [];
  const unit = unitFor(assets?.points.map((point) => point.value) ?? []);
  const colors = seriesColors(palette);
  const roe = payload.ratios.map((row) => row.roe_ttm);
  const hasRoe = roe.some((value) => value != null);

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
      {
        type: 'value',
        ...axisBase(palette),
        splitLine: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => `%${(value * 100).toFixed(0)}`,
        },
      },
    ],
    series: [
      {
        name: 'Toplam varlık',
        type: 'line',
        areaStyle: { opacity: 0.08, color: colors[0] },
        symbol: 'none',
        lineStyle: { width: 1.5, color: colors[0] },
        itemStyle: { color: colors[0] },
        data: assets?.points.map((point) =>
          point.value == null ? null : point.value / unit.divisor
        ),
      },
      {
        name: 'Özkaynak',
        type: 'line',
        areaStyle: { opacity: 0.12, color: colors[1] },
        symbol: 'none',
        lineStyle: { width: 1.5, color: colors[1] },
        itemStyle: { color: colors[1] },
        data: equity?.points.map((point) =>
          point.value == null ? null : point.value / unit.divisor
        ),
      },
      // Dropped rather than drawn flat at zero when trailing net income cannot
      // be measured — a 0% return line is a claim about the company.
      ...(hasRoe
        ? [
            {
              name: 'Özkaynak kârlılığı',
              type: 'line',
              yAxisIndex: 1,
              symbol: 'circle',
              symbolSize: 5,
              connectNulls: false,
              lineStyle: { width: 1.5, type: 'dashed', color: palette['--oi-price'] },
              itemStyle: { color: palette['--oi-price'] },
              data: roe,
            },
          ]
        : []),
    ],
  };

  return <ReactECharts option={option} style={{ height: 260 }} notMerge lazyUpdate />;
}
