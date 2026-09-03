'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';

import { formatCompact, formatSignedPercent } from '@/lib/bist-format';
import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';
import {
  QUADRANTS,
  QUADRANT_LABEL,
  QUADRANT_NOTE,
  type FuturesPoint,
  type Quadrant,
} from '@/lib/bist-positioning';

interface FuturesQuadrantProps {
  points: FuturesPoint[];
  height?: number;
  selected?: Quadrant;
  onSelectQuadrant: (quadrant: Quadrant | undefined) => void;
  onSelectTicker: (ticker: string) => void;
}

/**
 * Who opened what, and who closed it.
 *
 * Open interest is the count of contracts outstanding, so its direction says
 * whether positions were opened or closed, and the price direction says which
 * side had to pay to do it. Together they name four different events that a
 * single "open interest moved" column flattens into one: new longs, new shorts,
 * shorts being squeezed out, and longs giving up.
 *
 * Colour and fill encode the two axes rather than the four categories, which is
 * what keeps this inside the codebase's rule that colour means direction,
 * status or identity and never category. Green and red are the price, exactly
 * as everywhere else on the board. **Filled means open interest rose — money
 * arriving; hollow means it fell — money leaving.** So the two green quadrants
 * are told apart by fill and by which side of the axis they sit on, not by a
 * fifth and sixth hue that would have to mean something new.
 */
export default function FuturesQuadrant({
  points,
  height = 300,
  selected,
  onSelectQuadrant,
  onSelectTicker,
}: FuturesQuadrantProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const counts = useMemo(() => {
    const tally = new Map<Quadrant, number>();
    for (const point of points) tally.set(point.quadrant, (tally.get(point.quadrant) ?? 0) + 1);
    return tally;
  }, [points]);

  const option = useMemo(() => {
    const largest = points.reduce((max, point) => Math.max(max, point.openInterest), 0);
    const sizeOf = (openInterest: number) =>
      largest <= 0 ? 6 : 6 + 14 * Math.sqrt(openInterest / largest);

    const data = points.map((point) => {
      const up = point.changePct >= 0;
      const colour = up ? palette['--up'] : palette['--down'];
      const opening = point.openInterestChange > 0;
      const dimmed = selected !== undefined && selected !== point.quadrant;
      return {
        value: [point.openInterestChangeRatio ?? 0, point.changePct],
        name: point.ticker,
        point,
        symbolSize: sizeOf(point.openInterest),
        itemStyle: opening
          ? { color: colour, opacity: dimmed ? 0.15 : 0.8, borderWidth: 0 }
          : {
              color: 'transparent',
              borderColor: colour,
              borderWidth: 1.5,
              opacity: dimmed ? 0.2 : 0.95,
            },
      };
    });

    const axisLine = {
      symbol: 'none' as const,
      silent: true,
      lineStyle: { color: palette['--border-strong'], width: 1 },
      label: { show: false },
    };

    // Borsa İstanbul lists single-stock futures on very few names — six joined
    // the equity board the day this was written. At that density the tickers
    // fit on the chart, and a labelled point is worth more than a hover target;
    // past a dozen they would overlap into noise and the tooltip takes over.
    const labelled = points.length <= 12;

    // Axis precision has to follow the span, not a fixed choice. Across the
    // whole board these moves run to eighteen percent and whole numbers read
    // cleanly; filtered to one name the span can be half a percentage point,
    // and whole numbers print the same tick label six times down the axis.
    const ratios = points.map((point) => point.openInterestChangeRatio ?? 0);
    const span = Math.max(...ratios, 0) - Math.min(...ratios, 0);
    const ratioDecimals = span < 0.02 ? 2 : span < 0.1 ? 1 : 0;

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 8, right: 56, top: 16, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (params: { data: { point: FuturesPoint } }) => {
          const point = params.data.point;
          return [
            `<strong>${point.ticker}</strong> · ${point.sector}`,
            QUADRANT_LABEL[point.quadrant],
            `Açık pozisyon: ${formatCompact(point.openInterest, 1)}`,
            `AP değişimi: ${formatSignedPercent(point.openInterestChangeRatio)} (${point.openInterestChange > 0 ? '+' : ''}${formatCompact(point.openInterestChange, 1)})`,
            `Fiyat: ${formatSignedPercent(point.changePct)}`,
          ].join('<br/>');
        },
      },
      xAxis: {
        // Named in the panel header, not on the canvas: an in-plot axis name
        // sits exactly where the labelled points do.
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => formatSignedPercent(value, ratioDecimals),
        },
        splitLine: { lineStyle: { color: palette['--border'], opacity: 0.35 } },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => formatSignedPercent(value, 2),
        },
        splitLine: { lineStyle: { color: palette['--border'], opacity: 0.35 } },
      },
      series: [
        {
          type: 'scatter',
          data,
          label: {
            show: labelled,
            position: 'right',
            formatter: (params: { name: string }) => params.name,
            color: palette['--fg-muted'],
            fontSize: 10,
          },
          labelLayout: { hideOverlap: true },
          // The two zero lines are the quadrant boundaries. They are the only
          // reference the reader needs; a grid of four tinted rectangles would
          // spend colour on a division the axes already make.
          markLine: { ...axisLine, data: [{ xAxis: 0 }, { yAxis: 0 }] },
        },
      ],
    };
  }, [points, palette, selected]);

  return (
    <div className="flex h-full flex-col">
      {points.length === 0 ? (
        <p
          style={{ height }}
          className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
        >
          Açık pozisyonu ve fiyatı birlikte hareket eden vadeli sözleşme yok.
        </p>
      ) : (
        <>
          <p className="sr-only">
            Vadeli sözleşmesi olan {points.length} hisse, açık pozisyon değişimi ve fiyat yönüne
            göre dört gruba ayrılmış. Sayılar aşağıdaki düğmelerde.
          </p>
          <ReactECharts
            option={option}
            notMerge
            opts={{ renderer: 'canvas' }}
            style={{ height, width: '100%' }}
            onEvents={{
              click: (params: { data?: { point?: FuturesPoint } }) => {
                const ticker = params.data?.point?.ticker;
                if (ticker) onSelectTicker(ticker);
              },
            }}
          />
        </>
      )}

      {/* The quadrants as real buttons rather than clickable regions of the
          canvas: this is the panel's legend and its filter at once, and a
          canvas hit-test is reachable by neither the keyboard nor a reader. */}
      <div className="grid shrink-0 grid-cols-2 gap-px border-t border-line bg-line">
        {QUADRANTS.map((quadrant) => {
          const active = selected === quadrant;
          const count = counts.get(quadrant) ?? 0;
          return (
            <button
              key={quadrant}
              type="button"
              disabled={count === 0}
              aria-pressed={active}
              title={QUADRANT_NOTE[quadrant]}
              onClick={() => onSelectQuadrant(active ? undefined : quadrant)}
              className={`flex items-baseline justify-between gap-2 px-3 py-1.5 text-left transition-colors disabled:cursor-default disabled:opacity-40 ${
                active ? 'bg-surface-2 text-fg' : 'bg-surface text-fg-muted enabled:hover:text-fg'
              }`}
            >
              <span className="truncate text-2xs">{QUADRANT_LABEL[quadrant]}</span>
              <span className="tabnum text-sm font-semibold">{count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
