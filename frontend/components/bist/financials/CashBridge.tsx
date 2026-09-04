'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useState } from 'react';

import type { BistFinancials } from '@/lib/bist-api';
import { type Basis, quarterSeries, unitFor } from '@/lib/bist-financials';
import { FALLBACK, type Palette, readPalette } from '@/lib/chart-palette';

import { axisBase, gridBase, legendBase, seriesColors, tooltipBase } from './chart-base';

/**
 * Whether reported profit arrives as cash.
 *
 * Two bars and a ratio line on a second axis. The panel exists because a
 * Turkish industrial can report a good quarter entirely in receivables, and the
 * income statement above says nothing about it — a conversion ratio under 1.0
 * sustained across four quarters is the single most useful thing on this board
 * that a P&L chart cannot show.
 */
export default function CashBridge({ payload, basis }: { payload: BistFinancials; basis: Basis }) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const [ocf, netIncome] = quarterSeries(payload, basis, ['ocf', 'net_income']);
  const periods = ocf?.points.map((point) => point.period) ?? [];
  const unit = unitFor([
    ...(ocf?.points.map((p) => p.value) ?? []),
    ...(netIncome?.points.map((p) => p.value) ?? []),
  ]);
  const colors = seriesColors(palette);
  const conversion = payload.ratios.map((row) => row.cash_conversion);

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
        name: 'x',
        ...axisBase(palette),
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'Faaliyet nakit akışı',
        type: 'bar',
        itemStyle: { color: colors[1] },
        data: ocf?.points.map((point) => (point.value == null ? null : point.value / unit.divisor)),
      },
      {
        name: 'Net kâr',
        type: 'bar',
        itemStyle: { color: colors[0] },
        data: netIncome?.points.map((point) =>
          point.value == null ? null : point.value / unit.divisor
        ),
      },
      {
        name: 'Nakde dönüşüm',
        type: 'line',
        yAxisIndex: 1,
        symbol: 'circle',
        symbolSize: 5,
        connectNulls: false,
        lineStyle: { width: 1.5, color: colors[2] },
        itemStyle: { color: colors[2] },
        // A reference at 1.0 would need a markLine per theme; the axis label
        // and the panel's own legend carry the reading instead.
        data: conversion,
      },
    ],
  };

  return <ReactECharts option={option} style={{ height: 260 }} notMerge lazyUpdate />;
}
