'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';

import { formatCompact, formatNumber, formatSignedPercent } from '@/lib/bist-format';
import {
  CURVE_SHAPE_LABEL,
  CURVE_SHAPE_NOTE,
  curveShape,
  expiryLabel,
  type TermPoint,
} from '@/lib/bist-viop';
import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';

interface ViopTermCurveProps {
  underlying: string;
  points: TermPoint[];
  height?: number;
}

/**
 * One underlying's strip, front month to back.
 *
 * The reading the table cannot produce at any sort order. Every contract on a
 * strip is the same asset at a different date, so the shape of the line between
 * them is the market's own price of time — and the table shows the same asset
 * six times with no way to see whether those six prices form a slope, a step or
 * a kink.
 *
 * **The shape is drawn without being read as sentiment, and that restraint is
 * the panel's whole point.** Turkish rates make the cost of carry large, so a
 * strip settling above spot is arithmetic; a chart that coloured contango green
 * would be reporting the policy rate as bullishness every single day. The
 * legend says which of the three shapes this is and the caption says what it
 * means, and neither takes a direction.
 *
 * Settlement rather than last, for the reason `termCurve` records: the far
 * months can go a session without a trade, and a curve built from last prices
 * is a line between two different moments.
 */
export default function ViopTermCurve({ underlying, points, height = 240 }: ViopTermCurveProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const shape = useMemo(() => curveShape(points), [points]);

  const option = useMemo(() => {
    const labels = points.map((point) => expiryLabel(point.expiryDate));

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 8, right: 16, top: 20, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (params: { dataIndex: number }[]) => {
          const point = points[params[0]?.dataIndex ?? 0];
          if (!point) return '';
          return [
            `<strong>${underlying}</strong> · ${point.expiry}`,
            `Uzlaşma: ${formatNumber(point.settlement, 4)}`,
            `Yakın vadeye göre: ${formatSignedPercent(point.basis, 2)}`,
            `Açık pozisyon: ${formatCompact(point.openInterest, 1)}`,
          ].join('<br/>');
        },
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisTick: { show: false },
        axisLabel: { color: palette['--fg-subtle'], fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        // A settlement curve spans a few percent of a large number, so a
        // zero-based axis would draw six points as one flat line and delete the
        // only thing this panel shows.
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => formatNumber(value, value >= 100 ? 0 : 2),
        },
        splitLine: { lineStyle: { color: palette['--border'], opacity: 0.35 } },
      },
      series: [
        {
          type: 'line',
          data: points.map((point) => point.settlement),
          // One neutral line. The curve's direction is the reading and colouring
          // it up or down would state a verdict the shape does not carry.
          lineStyle: { color: palette['--oi-price'], width: 2 },
          itemStyle: { color: palette['--oi-price'] },
          symbol: 'circle',
          // Open interest as the point size: the strip's shape and where the
          // book actually sits on it are two different questions, and a curve
          // whose back months are hairline dots is one nobody trades.
          symbolSize: (_value: number, params: { dataIndex: number }) =>
            sizeOf(points, params.dataIndex),
          smooth: false,
        },
      ],
    };
  }, [points, palette, underlying]);

  if (points.length === 0) {
    return (
      <p
        style={{ height }}
        className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
      >
        {underlying} için uzlaşma fiyatı okunabilen vade yok.
      </p>
    );
  }

  if (points.length === 1) {
    return (
      <p
        style={{ height }}
        className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
      >
        {underlying} tek vadeli — vade yapısı için en az iki sözleşme gerekiyor.
      </p>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <p className="sr-only">
        {underlying} sözleşmesinin {points.length} vadesi, uzlaşma fiyatına göre yakın vadeden uzak
        vadeye.
      </p>

      <ReactECharts
        option={option}
        notMerge
        opts={{ renderer: 'canvas' }}
        style={{ height, width: '100%' }}
      />

      {shape && (
        <div className="flex shrink-0 items-baseline justify-between gap-3 border-t border-line px-3 py-1.5">
          <span className="text-2xs text-fg-muted">
            {CURVE_SHAPE_LABEL[shape]} · {CURVE_SHAPE_NOTE[shape]}
          </span>
          <span className="tabnum shrink-0 text-2xs text-fg-subtle">
            {formatSignedPercent(points[points.length - 1].basis, 2)}
          </span>
        </div>
      )}
    </div>
  );
}

/** Open interest as a radius, so a thinly-held back month reads as one. */
function sizeOf(points: TermPoint[], index: number): number {
  const largest = points.reduce((max, point) => Math.max(max, point.openInterest ?? 0), 0);
  const value = points[index]?.openInterest ?? 0;
  if (largest <= 0) return 6;
  return 4 + 10 * Math.sqrt(value / largest);
}
