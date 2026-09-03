'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';

import { formatCompact, formatSignedPercent } from '@/lib/bist-format';
import { QUADRANTS, QUADRANT_LABEL, QUADRANT_NOTE, type Quadrant } from '@/lib/bist-positioning';
import { quadrantCounts, type ViopQuadrantPoint } from '@/lib/bist-viop';
import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';

interface ViopQuadrantProps {
  points: ViopQuadrantPoint[];
  height?: number;
  selected?: Quadrant;
  onSelectQuadrant: (quadrant: Quadrant | undefined) => void;
  onSelectUnderlying: (underlying: string) => void;
}

/**
 * Who opened what, and who closed it — contract by contract.
 *
 * Open interest is the count of contracts outstanding, so its direction says
 * whether positions were opened or closed, and the price direction says which
 * side had to pay to do it. Together they name four different events that the
 * table's single "AP değişim" column flattens into one: new longs, new shorts,
 * shorts being squeezed out, and longs giving up.
 *
 * Per contract rather than per underlying, which is what separates this panel
 * from the one on the positioning board. A strip routinely opens in its back
 * month while the front is being closed out — that is the roll, and summing the
 * two into one point per name deletes exactly the event a derivatives reader
 * came for.
 *
 * Colour and fill encode the two axes rather than the four categories, which is
 * what keeps this inside the codebase's rule that colour means direction,
 * status or identity and never category. Green and red are the price, exactly
 * as everywhere else on the board. **Filled means open interest rose — money
 * arriving; hollow means it fell — money leaving.** So the two green quadrants
 * are told apart by fill and by which side of the axis they sit on, not by a
 * fifth and sixth hue that would have to mean something new.
 */
export default function ViopQuadrant({
  points,
  height = 300,
  selected,
  onSelectQuadrant,
  onSelectUnderlying,
}: ViopQuadrantProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const counts = useMemo(() => quadrantCounts(points), [points]);

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
        value: [point.changeRatio, point.changePct],
        name: point.underlying,
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

    // Axis precision has to follow the span, not a fixed choice. Across the
    // whole board an open-interest ratio runs to tens of percent and whole
    // numbers read cleanly; filtered to one strip the span can be a fraction of
    // a percent, and whole numbers print the same tick label six times down the
    // axis.
    const ratios = points.map((point) => point.changeRatio);
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
        formatter: (params: { data: { point: ViopQuadrantPoint } }) => {
          const point = params.data.point;
          return [
            `<strong>${point.underlying}</strong> · ${point.expiry}`,
            QUADRANT_LABEL[point.quadrant],
            `Açık pozisyon: ${formatCompact(point.openInterest, 1)}`,
            `AP değişimi: ${formatSignedPercent(point.changeRatio)} (${point.openInterestChange > 0 ? '+' : ''}${formatCompact(point.openInterestChange, 1)})`,
            `Fiyat: ${formatSignedPercent(point.changePct)}`,
          ].join('<br/>');
        },
      },
      xAxis: {
        // Named in the panel header, not on the canvas: an in-plot axis name
        // sits exactly where the dense cluster of points does.
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
          // The board carries a hundred-odd contracts and several strips share
          // an underlying, so a label per point would draw the same six names
          // twenty times over. The tooltip carries the identity instead.
          label: { show: false },
          // The two zero lines are the quadrant boundaries. They are the only
          // reference the reader needs; a grid of four tinted rectangles would
          // spend colour on a division the axes already make.
          markLine: {
            symbol: 'none' as const,
            silent: true,
            lineStyle: { color: palette['--border-strong'], width: 1 },
            label: { show: false },
            data: [{ xAxis: 0 }, { yAxis: 0 }],
          },
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
          Açık pozisyonu ve fiyatı birlikte hareket eden sözleşme yok.
        </p>
      ) : (
        <>
          <p className="sr-only">
            {points.length} sözleşme, açık pozisyon değişimi ve fiyat yönüne göre dört gruba
            ayrılmış. Sayılar aşağıdaki düğmelerde.
          </p>
          <ReactECharts
            option={option}
            notMerge
            opts={{ renderer: 'canvas' }}
            style={{ height, width: '100%' }}
            onEvents={{
              click: (params: { data?: { point?: ViopQuadrantPoint } }) => {
                const underlying = params.data?.point?.underlying;
                if (underlying) onSelectUnderlying(underlying);
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
          const count = counts[quadrant];
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
