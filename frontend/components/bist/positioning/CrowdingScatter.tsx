'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';

import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';
import {
  formatCompactTry,
  formatNumber,
  formatPercent,
  formatSignedPercent,
} from '@/lib/bist-format';
import { MIN_FREE_FLOAT, MIN_RELATIVE_VOLUME, type CrowdingPoint } from '@/lib/bist-positioning';

interface CrowdingScatterProps {
  points: CrowdingPoint[];
  height?: number;
  onSelect: (ticker: string) => void;
}

/**
 * Crowding, as the two quantities it is actually made of.
 *
 * The board ranks by `relative_volume / free_float_pct`, and for a long time
 * that ratio was one more column of digits — a number the reader had to take on
 * faith. On two axes it stops being a score and becomes a place: the top-left
 * is unusual volume against a float too small to absorb it, and the eye finds
 * that corner without being told which number is large.
 *
 * The x axis is logarithmic because free float is not linearly distributed —
 * most of Borsa İstanbul sits between a fifth and a half, with a long thin tail
 * down toward the holding structures. On a linear axis the whole board would
 * pile into the right half and the corner this panel exists for would be a
 * smear against the y axis.
 *
 * The two service thresholds are drawn rather than merely obeyed. A reader who
 * sees a name with obvious volume and no crowding score should be able to find
 * out why by looking, and "it is left of the float line" is an answer the
 * numbers alone never gave.
 */
export default function CrowdingScatter({ points, height = 300, onSelect }: CrowdingScatterProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const option = useMemo(() => {
    // Area, not radius, carries the market cap: doubling a radius quadruples the
    // ink, which would read as four times the company.
    const largest = points.reduce((max, point) => Math.max(max, point.marketCap ?? 0), 0);
    const loudest = points.reduce((max, point) => Math.max(max, point.relativeVolume), 0);
    const sizeOf = (cap: number | null) => {
      if (!cap || largest <= 0) return 5;
      return 5 + 17 * Math.sqrt(cap / largest);
    };

    const data = points.map((point) => {
      const scored = point.crowding !== null;
      const direction =
        point.changePct === null
          ? palette['--fg-subtle']
          : point.changePct >= 0
            ? palette['--up']
            : palette['--down'];
      return {
        value: [point.freeFloat, point.relativeVolume],
        name: point.ticker,
        point,
        symbolSize: sizeOf(point.marketCap),
        itemStyle: {
          // Unscored names stay on the chart but recede. Removing them would
          // hide the very population the threshold lines are there to explain.
          color: scored ? direction : palette['--fg-subtle'],
          opacity: scored ? 0.75 : 0.28,
          borderWidth: 0,
        },
      };
    });

    const threshold = {
      symbol: 'none' as const,
      label: { color: palette['--fg-subtle'], fontSize: 10 },
      lineStyle: { color: palette['--border-strong'], type: 'dashed' as const, width: 1 },
    };

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 8, right: 20, top: 20, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (params: { data: { point: CrowdingPoint } }) => {
          const point = params.data.point;
          const rows = [
            `<strong>${point.ticker}</strong> · ${point.sector}`,
            `Halka açık: ${formatPercent(point.freeFloat)}`,
            `Nispi hacim: ${formatNumber(point.relativeVolume, 2)}×`,
            `Değişim: ${formatSignedPercent(point.changePct)}`,
            `Piyasa değeri: ${formatCompactTry(point.marketCap)}`,
            point.crowding === null
              ? 'Kalabalıklık: ölçülemiyor'
              : `Kalabalıklık: ${formatNumber(point.crowding, 1)}`,
          ];
          return rows.join('<br/>');
        },
      },
      xAxis: {
        // No axis names: the panel header already states both encodings, and
        // ECharts anchors a `name` inside the plot rectangle where it lands on
        // top of the very corner this chart exists to show.
        type: 'log',
        min: 0.01,
        max: 1,
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => formatPercent(value, 0),
        },
        splitLine: { show: false },
      },
      yAxis: {
        // Logarithmic, like the x axis, because relative volume is a ratio and
        // one name at twelve times its usual turnover would otherwise flatten
        // the entire 0.5×–2.5× population — where the whole board lives — into
        // the bottom eighth of the panel. On a log scale 2× and 0.5× sit
        // equally far from normal, which is what a ratio actually means.
        type: 'log',
        min: 0.1,
        // ECharts rounds a log axis out to the next decade, which turned a
        // board topping out near twelve into an axis reaching a hundred and
        // spent the upper half of the panel on empty space.
        max: Math.max(2, Math.ceil(loudest)),
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => `${formatNumber(value, 1)}×`,
        },
        splitLine: { lineStyle: { color: palette['--border'], type: 'dashed', opacity: 0.5 } },
      },
      series: [
        {
          type: 'scatter',
          data,
          markLine: {
            ...threshold,
            silent: true,
            data: [
              {
                xAxis: MIN_FREE_FLOAT,
                label: { ...threshold.label, formatter: 'float tabanı', position: 'end' },
              },
              {
                yAxis: MIN_RELATIVE_VOLUME,
                label: {
                  ...threshold.label,
                  formatter: 'normal hacim',
                  position: 'insideStartTop',
                },
              },
            ],
          },
        },
      ],
    };
  }, [points, palette]);

  if (points.length === 0) {
    return (
      <p
        style={{ height }}
        className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
      >
        Halka açıklık ve hacim birlikte ölçülebilen hisse yok.
      </p>
    );
  }

  const crowded = points.filter((point) => point.crowding !== null).length;

  return (
    <>
      {/* The chart is a canvas and says nothing to a screen reader. The table
          below the board carries the same rows in full; this is the shape. */}
      <p className="sr-only">
        {points.length} hissenin halka açıklığı ve nispi hacmi. {crowded} tanesi ölçülebilir
        kalabalıklık taşıyor. Tam liste sayfanın altındaki tabloda.
      </p>
      <ReactECharts
        option={option}
        notMerge
        opts={{ renderer: 'canvas' }}
        style={{ height, width: '100%' }}
        onEvents={{
          click: (params: { data?: { point?: CrowdingPoint } }) => {
            const ticker = params.data?.point?.ticker;
            if (ticker) onSelect(ticker);
          },
        }}
      />
    </>
  );
}
