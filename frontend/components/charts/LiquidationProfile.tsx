'use client';

import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle, Info, RefreshCw } from 'lucide-react';

import { useLiquidationProfile } from '@/hooks/queries';
import type { LiquidationVenue } from '@/lib/api';
import { compactUsd, FALLBACK, parseHex, readPalette, type Palette } from '@/lib/chart-palette';
import {
  binPrices,
  cumulativeFromSpot,
  formatBucket,
  spotBin,
  stackByTier,
} from '@/lib/liquidation-profile';

/**
 * One standing liquidation book, drawn against price instead of against time.
 *
 * Its two siblings on this page answer historical questions — where liquidity
 * has been, how long it survived. This one answers the question a position
 * actually has: if price goes there, how much gets liquidated on the way. The
 * bars are the book at each price, split by the leverage that put it there; the
 * curves are those bars accumulated outward from spot, which is the number that
 * matters when the move is already happening.
 *
 * The venue and the window are props rather than controls, because
 * `LiquidationMaps` stacks three of these to be read against each other. A
 * per-pane selector would let a reader put the same venue in two panes and
 * conclude nothing, and would let the windows drift apart, which is worse: two
 * books modelled over different amounts of history are not comparable at all.
 */

/**
 * Hue per leverage tier, cool to hot.
 *
 * Leverage is ordinal, so the ramp is one too, and it runs the direction the
 * risk does: the 10x band is background, the 125x band is the one that goes
 * first. `--up` green and `--down` red are spent on the cumulative curves, so
 * neither appears here.
 *
 * Stops rather than one colour per tier, because the tier count belongs to the
 * payload. It went from four to ten when the model's leverage table did, and a
 * fixed list would have quietly painted six of the bands the same fallback grey.
 *
 * Eight of them for four visible bands — blue, violet, gold, orange — because
 * the ramp is walked in RGB and violet blended halfway into gold is a warm
 * grey. Doubling each band's stops means no tier is ever sampled at that
 * midpoint: the pair inside a band separates its tiers by lightness, and the
 * crossing between two bands is stepped over rather than mixed through.
 */
const TIER_RAMP = [
  '#8fb8ec',
  '#5a86dd',
  '#8d84e8',
  '#6a5fd6',
  '#e6c25a',
  '#d9a834',
  '#e08a45',
  '#d9643a',
];

/**
 * `TIER_RAMP` sampled at `index` of `count`, as an `rgb()` string.
 *
 * A lone tier is drawn at the ramp's cool end rather than at its middle: with
 * nothing to compare it against, the hue carries no information, and the
 * coldest one is the least alarming thing to say with it.
 */
function tierColour(index: number, count: number): string {
  const t = count > 1 ? (index / (count - 1)) * (TIER_RAMP.length - 1) : 0;
  const lower = Math.min(Math.floor(t), TIER_RAMP.length - 2);
  const local = t - lower;
  const from = parseHex(TIER_RAMP[lower]);
  const to = parseHex(TIER_RAMP[lower + 1]);
  const [r, g, b] = [0, 1, 2].map((axis) =>
    Math.round(from[axis] + (to[axis] - from[axis]) * local)
  );
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Share of a category a bar leaves empty.
 *
 * Not zero, which was the first attempt and the wrong one: touching bars merge
 * into one continuous field of colour, and a profile stops looking like a set
 * of measurements at prices and starts looking like a painted band.
 */
const BAR_GAP = '34%';

/** `hex` at `alpha`, for fills the canvas has to be handed as a literal. */
function fade(hex: string, alpha: number): string {
  const [r, g, b] = parseHex(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * A cumulative curve's fill, fading out downward.
 *
 * A flat tint reads as a filled region — a second object on the chart, and a
 * heavy one at this size. Fading it to nothing keeps the fill as what it is:
 * shading that belongs to the line above it.
 */
function areaFade(hex: string) {
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: fade(hex, 0.26) },
      { offset: 1, color: fade(hex, 0) },
    ],
  };
}

interface TooltipEntry {
  seriesName?: string;
  value?: number | null;
  color?: string;
  axisValue?: string;
}

export interface LiquidationProfileProps {
  symbol: string;
  /** Whose book to model. */
  venue: LiquidationVenue;
  /** What to call it before the payload arrives and names itself. */
  label: string;
  /** Candle interval the model runs on; invisible here, it only sets the span. */
  interval: string;
  /** Bars of history, and so how far back a standing level may have opened. */
  columns: number;
  /** Only the topmost pane carries one; three identical legends is furniture. */
  showLegend?: boolean;
  className?: string;
}

export default function LiquidationProfile({
  symbol,
  venue,
  label,
  interval,
  columns,
  showLegend = false,
  className = '',
}: LiquidationProfileProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);

  // Tokens live on the document, so they can only be read after hydration.
  useEffect(() => {
    setPalette(readPalette());
  }, []);

  const { data, isLoading, isError, error, refetch } = useLiquidationProfile(
    symbol,
    interval,
    columns,
    venue
  );

  const option = useMemo(() => {
    if (!data || !data.bins || !data.levels.length) return undefined;

    const { levels, bins, price_min, bin_size, price, leverage_tiers } = data;

    const labels = binPrices(bins, price_min, bin_size).map(formatBucket);
    const spot = spotBin(price, price_min, bin_size, bins);
    const stack = stackByTier(levels, bins, leverage_tiers.length);
    const { long, short } = cumulativeFromSpot(levels, bins, spot);

    const axisLabel = {
      color: palette['--fg-subtle'],
      fontSize: 10,
      formatter: (value: number) => compactUsd(value),
    };

    return {
      backgroundColor: 'transparent',
      animation: false,
      // Headroom for the mark-line's price, which is drawn above the top of
      // the grid rather than inside it — at ten pixels the panes without a
      // legend were clipping it in half.
      grid: { left: 6, right: 6, top: showLegend ? 42 : 24, bottom: 6, containLabel: true },
      legend: {
        show: showLegend,
        top: 2,
        itemWidth: 8,
        itemHeight: 8,
        itemGap: 12,
        textStyle: { color: palette['--fg-muted'], fontSize: 10 },
        inactiveColor: palette['--fg-subtle'],
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        borderWidth: 1,
        padding: [6, 9],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (params: TooltipEntry[]) => {
          const rows = params
            .filter((entry) => typeof entry.value === 'number' && entry.value > 0)
            .map(
              (entry) =>
                `<span style="color:${entry.color}">■</span> ${entry.seriesName}` +
                `&nbsp;&nbsp;<b>${compactUsd(entry.value as number)}</b>`
            );
          if (!rows.length) return '';
          const head = `<div style="color:${palette['--fg-muted']}">$${params[0]?.axisValue ?? ''}</div>`;
          return [head, ...rows].join('<br/>');
        },
      },
      xAxis: {
        type: 'category',
        data: labels,
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisTick: { show: false },
        axisLabel: { color: palette['--fg-subtle'], fontSize: 10, hideOverlap: true },
      },
      yAxis: [
        {
          type: 'value',
          // Both axes are pinned to zero. ECharts picks a "nice" floor from the
          // data, which on a book whose bars are all large lands well above the
          // origin — and a bar chart cut off below its base is a lie about
          // proportion, not a crop.
          min: 0,
          // Liquidations at one price. Split lines only, because the bars are
          // read against each other far more often than against the axis.
          splitLine: { lineStyle: { color: palette['--border'], type: 'dashed', opacity: 0.5 } },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel,
        },
        {
          type: 'value',
          position: 'right',
          min: 0,
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel,
        },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }],
      series: [
        ...leverage_tiers.map((tier, index) => ({
          name: `${tier}x`,
          type: 'bar',
          stack: 'book',
          data: stack[index],
          itemStyle: { color: tierColour(index, leverage_tiers.length) },
          barCategoryGap: BAR_GAP,
        })),
        {
          name: 'Cumulative longs',
          type: 'line',
          yAxisIndex: 1,
          data: long,
          symbol: 'none',
          // The curve stops at spot rather than jumping the gap to the far
          // side, where it would describe the opposite side's book.
          connectNulls: false,
          lineStyle: { color: palette['--down'], width: 1.25, opacity: 0.9 },
          itemStyle: { color: palette['--down'] },
          areaStyle: { color: areaFade(palette['--down']) },
          z: 5,
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ xAxis: spot }],
            lineStyle: { color: palette['--fg-muted'], type: 'dashed', width: 1 },
            label: {
              formatter: `$${formatBucket(price)}`,
              color: palette['--fg-muted'],
              fontSize: 10,
              position: 'insideEndTop',
              // ECharts rotates a mark-line label to run along the line, which
              // on a vertical one prints the price sideways.
              rotate: 0,
              distance: 3,
            },
          },
        },
        {
          name: 'Cumulative shorts',
          type: 'line',
          yAxisIndex: 1,
          data: short,
          symbol: 'none',
          connectNulls: false,
          lineStyle: { color: palette['--up'], width: 1.25, opacity: 0.9 },
          itemStyle: { color: palette['--up'] },
          areaStyle: { color: areaFade(palette['--up']) },
          z: 5,
        },
      ],
    };
  }, [data, palette, showLegend]);

  return (
    <div className={`flex flex-col min-h-0 ${className}`}>
      {/* Pane header — the window, and what the window contains. The venue and
          the market are named once by the page above, not three times here. */}
      <div className="shrink-0 flex items-center gap-2 px-3 h-7 border-b border-line bg-surface">
        {/* The payload's own name, not the prop: an aggregate lists only the
            venues that actually answered, so a feed going down says so here
            rather than being averaged into silence. */}
        <span className="text-2xs font-mono text-fg">{data?.exchange || label}</span>

        {data !== undefined && data.price > 0 && (
          <span className="text-2xs font-mono tabnum text-fg-subtle">
            ${data.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
          </span>
        )}

        {data !== undefined && data.levels.length > 0 && (
          <span className="text-2xs font-mono tabnum text-fg-subtle whitespace-nowrap">
            <span className="text-down">{compactUsd(data.total_long)}</span> below ·{' '}
            <span className="text-up">{compactUsd(data.total_short)}</span> above
          </span>
        )}

        {data !== undefined && data.stats_from_column > 0 && (
          <span
            className="px-1.5 py-0.5 rounded text-2xs bg-surface-2 text-fg-subtle"
            title={`The oldest ${data.stats_from_column} candles predate OKX's open-interest and long/short history — modelled from volume alone with a neutral split.`}
          >
            partial
          </span>
        )}
      </div>

      <div className="relative flex-1 min-h-0 w-full">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center gap-2">
            <RefreshCw className="w-3 h-3 animate-spin text-fg-muted" />
            <span className="text-2xs text-fg-muted">Modelling the {label} book…</span>
          </div>
        ) : isError ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-6 text-center">
            <AlertTriangle className="w-3 h-3 text-down" />
            <span className="text-2xs text-fg-muted">
              {error instanceof Error ? error.message : 'Could not load this window.'}
            </span>
            <button
              onClick={() => refetch()}
              className="mt-1 px-2 py-0.5 rounded border border-line text-2xs text-fg-muted hover:text-fg"
            >
              Retry
            </button>
          </div>
        ) : !option ? (
          <div className="absolute inset-0 flex items-center justify-center px-6 text-center">
            <span className="text-2xs text-fg-muted">
              No standing levels for {symbol} on {label}.
            </span>
          </div>
        ) : (
          <ReactECharts
            option={option}
            style={{ height: '100%', width: '100%' }}
            opts={{ renderer: 'canvas' }}
            notMerge
          />
        )}
      </div>
    </div>
  );
}
