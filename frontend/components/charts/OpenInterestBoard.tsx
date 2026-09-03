'use client';

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import * as echarts from 'echarts';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle, Info, RefreshCw } from 'lucide-react';

import { useOpenInterest } from '@/hooks/queries';
import type { OpenInterestBoard as Board } from '@/lib/api';
import { compactUsd, FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';
import {
  aggregateChangePct,
  oiToMarketCapRatio,
  venueShare,
  windowSummary,
  withAlpha,
} from '@/lib/open-interest';

/**
 * Open interest against price — the input the liquidation views model from.
 *
 * The three views on the rest of this page all answer questions about *where*
 * leveraged positions sit. This one answers whether there are more of them than
 * there were. Price rising on rising open interest is new money taking a side;
 * price rising on falling open interest is shorts being squeezed out of one.
 * The two are indistinguishable on a candle chart and opposite in what they
 * imply, which is the whole reason this pane exists.
 *
 * Four panes, one payload. The top two draw the same quantity twice — summed,
 * then split by venue — because the sum answers "how much" and the split
 * answers "who", and reading one against the other is how a venue-specific
 * unwind gets told apart from a market-wide one. The two below are derivations:
 * the change bars turn a slope into something countable, and the market-cap
 * ratio says whether a given figure is large for this asset or merely large.
 */

const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT'] as const;

// No weekly: neither provider publishes one, and a control that silently
// served daily instead would be a claim about resolution the data cannot
// honour. The slider under the first pane is how a multi-year daily series
// gets read at that span.
const INTERVALS = ['1h', '4h', '1d'] as const;
type Interval = (typeof INTERVALS)[number];

/**
 * All four panes share one zoom.
 *
 * They are four charts drawing one window, so a scrub that moved only the pane
 * under the cursor would put four different time ranges on screen at once and
 * quietly invite the reader to compare them.
 */
const ZOOM_GROUP = 'open-interest-board';

/** Venue → palette token, by stacking position. */
const VENUE_TOKENS = ['--oi-venue-1', '--oi-venue-2', '--oi-venue-3'] as const;

interface TooltipEntry {
  axisValue: number;
  dataIndex: number;
  value: number | (number | null)[] | null;
  seriesName?: string;
  color?: string;
}

interface OpenInterestBoardProps {
  className?: string;
}

export default function OpenInterestBoard({ className = '' }: OpenInterestBoardProps) {
  const [symbol, setSymbol] = useState<string>(SYMBOLS[0]);
  // Daily by default: with a Coinalyze key configured this is the multi-year
  // chart the board exists to draw, and the slider under the first pane is how
  // it gets read. Without a key it degrades honestly rather than silently —
  // Binance keeps thirty days where OKX keeps a hundred and eighty, so the
  // aggregate starts late and the `30d` badge in the toolbar says why.
  const [interval, setInterval] = useState<Interval>('1d');
  const [palette, setPalette] = useState<Palette>(FALLBACK);

  // Tokens live on the document, so they can only be read after hydration —
  // the canvas renderer is handed literal colours and ignores `var(--token)`.
  useEffect(() => {
    setPalette(readPalette());
  }, []);

  const { data, isLoading, isFetching, isError, error, refetch } = useOpenInterest(
    symbol,
    interval
  );

  // Joining the four charts has to happen after each has an instance, and
  // `connect` is idempotent, so every pane calls it as it becomes ready.
  const onChartReady = useCallback((instance: echarts.ECharts) => {
    instance.group = ZOOM_GROUP;
    echarts.connect(ZOOM_GROUP);
  }, []);

  const times = useMemo(() => (data?.candles ?? []).map((candle) => candle.time * 1000), [data]);

  const summary = useMemo(() => windowSummary(data?.aggregate ?? []), [data]);

  const shared = useMemo(() => buildShared(palette, data, times), [palette, data, times]);

  const aggregateOption = useMemo(() => {
    if (!data?.candles.length || !shared) return undefined;
    return {
      ...shared.base,
      // Extra room under this pane alone: it carries the slider every pane
      // is zoomed by, below its own time labels. And room above for the legend,
      // which names the two series sharing the plot — without it the amber line
      // is just a second line on an open-interest chart.
      grid: { ...shared.grid, top: 30, bottom: 48 },
      legend: {
        show: true,
        top: 2,
        left: 'center',
        icon: 'rect',
        itemWidth: 9,
        itemHeight: 9,
        itemGap: 16,
        data: ['Price', 'Open interest'],
        textStyle: { color: palette['--fg-muted'], fontSize: 10 },
        inactiveColor: palette['--fg-subtle'],
      },
      tooltip: {
        ...shared.tooltip,
        formatter: (params: TooltipEntry[]) => {
          const total = params.find((entry) => entry.seriesName === 'Open interest');
          const price = params.find((entry) => entry.seriesName === 'Price');
          const rows = [
            total && `Open interest&nbsp;&nbsp;<b>${compactUsd(numberAt(total))}</b>`,
            price && `Price&nbsp;&nbsp;<b>${usd(numberAt(price))}</b>`,
          ].filter(Boolean);
          return [shared.head(params[0]?.axisValue), ...rows].join('<br/>');
        },
      },
      xAxis: shared.xAxis,
      yAxis: shared.dualAxis,
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
        {
          type: 'slider',
          xAxisIndex: 0,
          height: 18,
          bottom: 4,
          filterMode: 'none',
          backgroundColor: 'transparent',
          borderColor: palette['--border'],
          fillerColor: withAlpha(palette['--oi-total'], 0.12),
          handleStyle: { color: palette['--border-strong'] },
          moveHandleStyle: { color: palette['--border-strong'] },
          dataBackground: {
            lineStyle: { color: palette['--border-strong'], width: 1 },
            areaStyle: { color: withAlpha(palette['--oi-total'], 0.2) },
          },
          selectedDataBackground: {
            lineStyle: { color: palette['--oi-total'], width: 1 },
            areaStyle: { color: withAlpha(palette['--oi-total'], 0.35) },
          },
          textStyle: { color: palette['--fg-subtle'], fontSize: 9 },
        },
      ],
      series: [
        {
          name: 'Open interest',
          type: 'line',
          showSymbol: false,
          connectNulls: false,
          lineStyle: { color: palette['--oi-total'], width: 1.2 },
          itemStyle: { color: palette['--oi-total'] },
          // Fading downward rather than filled flat. A solid block reaching the
          // axis swallows the price line wherever the two overlap, and open
          // interest is read as a shape at its top edge — the mass underneath
          // carries no information the edge does not.
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: withAlpha(palette['--oi-total'], 0.55) },
                { offset: 1, color: withAlpha(palette['--oi-total'], 0.02) },
              ],
            },
          },
          data: zip(times, data.aggregate),
          markArea: shared.uncovered,
          z: 2,
        },
        shared.priceSeries,
      ],
    };
  }, [data, palette, shared, times]);

  const venueOption = useMemo(() => {
    if (!data?.candles.length || !shared || !data.venues.length) return undefined;
    return {
      ...shared.base,
      grid: shared.grid,
      tooltip: {
        ...shared.tooltip,
        formatter: (params: TooltipEntry[]) => {
          const index = params[0]?.dataIndex ?? 0;
          const rows = venueShare(data.series, data.venues, index).map(
            ({ venue, value, share }) =>
              `<span style="color:${palette[VENUE_TOKENS[data.venues.indexOf(venue) % 3]]}">■</span>` +
              ` ${venue}&nbsp;&nbsp;<b>${compactUsd(value)}</b>` +
              `&nbsp;<span style="opacity:.6">${share.toFixed(0)}%</span>`
          );
          const price = params.find((entry) => entry.seriesName === 'Price');
          if (price) rows.push(`Price&nbsp;&nbsp;<b>${usd(numberAt(price))}</b>`);
          return [shared.head(params[0]?.axisValue), ...rows].join('<br/>');
        },
      },
      xAxis: shared.xAxis,
      yAxis: shared.dualAxis,
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }],
      series: [
        ...data.venues.map((venue, index) => {
          const colour = palette[VENUE_TOKENS[index % VENUE_TOKENS.length]];
          return {
            name: venue,
            type: 'line',
            stack: 'venues',
            showSymbol: false,
            // The legend marker reads `itemStyle`, not `lineStyle`. Without
            // this ECharts colours it from its own default palette and the
            // legend names a venue in a colour that appears nowhere on the
            // chart.
            itemStyle: { color: colour },
            // A venue that has not started yet leaves a hole rather than a
            // zero, so the stack thins to whoever was reporting instead of
            // vanishing — this pane is where the history the aggregate cannot
            // use stays visible.
            connectNulls: false,
            lineStyle: { color: colour, width: 1 },
            // Translucent, and fading downward. Three solid bands would read as
            // one shape; the fade keeps each boundary visible where they meet.
            areaStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: withAlpha(colour, 0.45) },
                  { offset: 1, color: withAlpha(colour, 0.04) },
                ],
              },
            },
            data: zip(times, data.series[venue] ?? []),
            z: 2,
          };
        }),
        shared.priceSeries,
      ],
    };
  }, [data, palette, shared, times]);

  const changeOption = useMemo(() => {
    if (!data?.candles.length || !shared) return undefined;
    const change = aggregateChangePct(data.aggregate);
    return {
      ...shared.base,
      grid: shared.grid,
      tooltip: {
        ...shared.tooltip,
        formatter: (params: TooltipEntry[]) => {
          const value = numberAt(params[0]);
          return [
            shared.head(params[0]?.axisValue),
            `Change&nbsp;&nbsp;<b>${value >= 0 ? '+' : ''}${value.toFixed(2)}%</b>`,
          ].join('<br/>');
        },
      },
      xAxis: shared.xAxis,
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: palette['--border'], type: 'dashed', opacity: 0.5 } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => `${value.toFixed(0)}%`,
        },
      },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }],
      series: [
        {
          name: 'Change',
          type: 'bar',
          data: zip(times, change),
          itemStyle: {
            color: (item: { value: (number | null)[] }) =>
              (item.value[1] ?? 0) >= 0 ? palette['--up'] : palette['--down'],
          },
        },
      ],
    };
  }, [data, palette, shared, times]);

  const ratioOption = useMemo(() => {
    if (!data?.candles.length || !shared || !data.market_cap.length) return undefined;
    const ratio = oiToMarketCapRatio(data.aggregate, data.market_cap);
    return {
      ...shared.base,
      grid: shared.grid,
      tooltip: {
        ...shared.tooltip,
        formatter: (params: TooltipEntry[]) =>
          [
            shared.head(params[0]?.axisValue),
            `OI / market cap&nbsp;&nbsp;<b>${numberAt(params[0]).toFixed(2)}%</b>`,
          ].join('<br/>'),
      },
      xAxis: shared.xAxis,
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: palette['--border'], type: 'dashed', opacity: 0.5 } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => `${value.toFixed(1)}%`,
        },
      },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }],
      series: [
        {
          name: 'OI / market cap',
          type: 'line',
          showSymbol: false,
          connectNulls: false,
          lineStyle: { color: palette['--oi-venue-3'], width: 1.25 },
          areaStyle: { color: withAlpha(palette['--oi-venue-3'], 0.16) },
          data: zip(times, ratio),
        },
      ],
    };
  }, [data, palette, shared, times]);

  const shallow = data?.source === 'venues';

  return (
    <div className={`flex flex-col w-full h-full bg-bg ${className}`}>
      {/* Toolbar */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-3 h-10 border-b border-line bg-surface overflow-x-auto">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base font-semibold text-fg truncate">Open Interest</span>

          <select
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            aria-label="Market"
            className="px-1.5 py-0.5 rounded text-2xs font-mono bg-surface-2 text-fg-muted border border-line hover:text-fg"
          >
            {SYMBOLS.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </select>

          {summary.latest !== null && (
            <span className="text-xs font-mono tabnum text-fg-muted">
              {compactUsd(summary.latest)}
              {summary.changePct !== null && (
                <span className={summary.changePct >= 0 ? 'text-up ml-1.5' : 'text-down ml-1.5'}>
                  {summary.changePct >= 0 ? '+' : ''}
                  {summary.changePct.toFixed(1)}%
                </span>
              )}
            </span>
          )}

          <span
            className="text-fg-subtle"
            title="Total notional held in open perpetual positions across Binance, OKX and Bybit, in USD. Rising open interest is new exposure; falling open interest is positions being closed or liquidated."
          >
            <Info className="w-3 h-3" />
          </span>

          {shallow && (
            <span
              className="px-1.5 py-0.5 rounded text-2xs bg-surface-2 text-fg-subtle"
              title="Served from the exchanges' own statistics endpoints, which keep about thirty days. A free Coinalyze API key (COINALYZE_API_KEY) extends this to the full daily history."
            >
              30d
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <div className="flex gap-0.5" role="group" aria-label="Interval">
            {INTERVALS.map((entry) => (
              <button
                key={entry}
                onClick={() => setInterval(entry)}
                className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                  interval === entry ? 'bg-surface-2 text-fg' : 'text-fg-subtle hover:text-fg-muted'
                }`}
              >
                {entry}
              </button>
            ))}
          </div>

          <button
            onClick={() => refetch()}
            disabled={isFetching}
            title="Refresh"
            className="p-1 rounded border border-line text-fg-muted hover:text-fg hover:border-line-strong disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Panes. The top two are given real height and the derivations sit below
          the fold, because the aggregate against price is what the board is
          for — four equal panes would make that one unreadable to save a
          scroll. */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {isLoading ? (
          <div className="h-full flex flex-col items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-fg-muted" />
            <span className="text-sm text-fg-muted">Loading open interest…</span>
          </div>
        ) : isError ? (
          <div className="h-full flex flex-col items-center justify-center gap-2 px-6 text-center">
            <AlertTriangle className="w-4 h-4 text-down" />
            <span className="text-sm text-fg-muted">
              {error instanceof Error ? error.message : 'Could not load open interest.'}
            </span>
            <button
              onClick={() => refetch()}
              className="mt-1 px-2.5 py-1 rounded-md border border-line text-sm text-fg-muted hover:text-fg"
            >
              Retry
            </button>
          </div>
        ) : !aggregateOption ? (
          <div className="h-full flex items-center justify-center px-6 text-center">
            <span className="text-sm text-fg-muted">
              No open-interest history for {symbol} on Binance, OKX or Bybit.
            </span>
          </div>
        ) : (
          <>
            <Pane
              title={`Aggregated ${data?.symbol ?? ''} Open Interest (USD)`}
              subtitle={data?.venues.join(' + ')}
              height="min(52vh, 420px)"
              option={aggregateOption}
              onChartReady={onChartReady}
            />
            <Pane
              title={`${data?.symbol ?? ''} Open Interest by Exchange (USD)`}
              height="min(46vh, 380px)"
              option={venueOption}
              onChartReady={onChartReady}
              legend={(data?.venues ?? []).map((venue, index) => (
                <span key={venue} className="flex items-center gap-1.5">
                  <span
                    className="w-2 h-2 rounded-[2px]"
                    style={{ background: palette[VENUE_TOKENS[index % VENUE_TOKENS.length]] }}
                  />
                  {venue}
                </span>
              ))}
            />
            <Pane
              title={`Open Interest Change (${data?.interval ?? ''})`}
              height="220px"
              option={changeOption}
              onChartReady={onChartReady}
            />
            <Pane
              title="Open Interest / Market Cap"
              subtitle={
                data?.circulating_supply
                  ? 'Market cap derived from circulating supply at each close'
                  : undefined
              }
              height="220px"
              option={ratioOption}
              empty="Circulating supply is unavailable for this asset."
              onChartReady={onChartReady}
            />
            <p className="px-3 py-2 text-2xs text-fg-subtle border-t border-line">
              Open interest is the notional standing in open perpetual positions on each venue, in
              USD. Bybit reports contracts rather than dollars and is converted at each bar&apos;s
              close.{' '}
              {data && data.coverage_from > 0 && (
                <>
                  The aggregate starts where every listed venue has history; before that only the
                  per-exchange pane is meaningful, since a sum over fewer books is not comparable to
                  the rest of the line.{' '}
                </>
              )}
              {shallow
                ? 'History is limited to what the exchanges keep, roughly thirty days.'
                : 'History comes from Coinalyze, which retains its daily series indefinitely.'}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

/** One titled chart block in the scrolling stack. */
function Pane({
  title,
  subtitle,
  height,
  option,
  empty = 'No data for this pane.',
  legend,
  onChartReady,
}: {
  title: string;
  subtitle?: string;
  height: string;
  option: Record<string, unknown> | undefined;
  empty?: string;
  /** Series key, rendered in the header rather than inside the canvas. */
  legend?: ReactNode;
  onChartReady: (instance: echarts.ECharts) => void;
}) {
  return (
    <section className="border-b border-line">
      <div className="flex items-baseline gap-2 px-3 pt-2">
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {subtitle && <span className="text-2xs text-fg-subtle truncate">{subtitle}</span>}
        {/* An ECharts legend is positioned against the canvas, which put this
            one a line below the title and on top of the right price axis. In
            the header it sits on the title's own baseline and cannot collide
            with anything the chart draws. */}
        {legend && (
          <div className="ml-auto flex items-center gap-3 shrink-0 text-2xs text-fg-muted">
            {legend}
          </div>
        )}
      </div>
      <div style={{ height }} className="w-full">
        {option ? (
          <ReactECharts
            option={option}
            style={{ height: '100%', width: '100%' }}
            opts={{ renderer: 'canvas' }}
            onChartReady={onChartReady}
            notMerge
          />
        ) : (
          <div className="h-full flex items-center justify-center px-6 text-center">
            <span className="text-2xs text-fg-subtle">{empty}</span>
          </div>
        )}
      </div>
    </section>
  );
}

/**
 * The option fragments every pane shares.
 *
 * Built once so the four charts cannot drift apart: they draw one window, and a
 * grid or an axis that differed by a few pixels between panes would misalign
 * bars against the area above them at exactly the moments a reader is trying to
 * line them up.
 */
function buildShared(palette: Palette, data: Board | undefined, times: number[]) {
  if (!data?.candles.length) return undefined;

  const axisLabel = { color: palette['--fg-subtle'], fontSize: 10 };

  return {
    base: {
      backgroundColor: 'transparent',
      animation: false,
    },
    // Fixed gutters, not `containLabel`. The four panes are read down a time
    // column, and `containLabel` sizes each grid to its own labels — "$18.00B"
    // on the top two, "1.2%" on the bottom two — so the same timestamp landed
    // at four different x positions. These are wide enough for the widest
    // label either axis formats.
    // `bottom` has to clear the time labels by hand now that the grid no
    // longer measures them.
    grid: { left: 66, right: 54, top: 16, bottom: 24 },
    xAxis: {
      type: 'time' as const,
      axisLine: { lineStyle: { color: palette['--border'] } },
      axisTick: { show: false },
      axisLabel: { ...axisLabel, hideOverlap: true },
    },
    dualAxis: [
      {
        type: 'value' as const,
        min: 0,
        splitLine: { lineStyle: { color: palette['--border'], type: 'dashed', opacity: 0.5 } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { ...axisLabel, formatter: (value: number) => compactUsd(value) },
      },
      {
        type: 'value' as const,
        position: 'right' as const,
        // Price gets its own scale and no split lines: it shares the plot with
        // an area whose magnitude is unrelated, and a second grid would turn
        // the pane into a lattice.
        scale: true,
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { ...axisLabel, formatter: (value: number) => compactUsd(value) },
      },
    ],
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'line' as const, lineStyle: { color: palette['--border-strong'] } },
      backgroundColor: palette['--surface'],
      borderColor: palette['--border'],
      borderWidth: 1,
      padding: [6, 9] as [number, number],
      textStyle: { color: palette['--fg'], fontSize: 11 },
    },
    priceSeries: {
      name: 'Price',
      type: 'line' as const,
      yAxisIndex: 1,
      showSymbol: false,
      lineStyle: { color: palette['--oi-price'], width: 1.1 },
      itemStyle: { color: palette['--oi-price'] },
      data: data.candles.map((candle) => [candle.time * 1000, candle.close]),
      z: 4,
    },
    /**
     * The bars before every venue had published, shaded out.
     *
     * Without it the aggregate steps up on the bar a venue first appears, and
     * nothing on the chart distinguishes that from positions being opened.
     */
    uncovered:
      data.coverage_from > 0
        ? {
            silent: true,
            itemStyle: { color: withAlpha(palette['--fg-subtle'], 0.1) },
            data: [[{ xAxis: times[0] }, { xAxis: times[data.coverage_from] }]],
          }
        : undefined,
    head: (axisValue: number | undefined) =>
      `<div style="color:${palette['--fg-muted']}">${formatStamp(axisValue)}</div>`,
  };
}

/** `[timeMs, value]` pairs, keeping nulls so a gap stays a gap. */
function zip(times: number[], values: (number | null)[]): [number, number | null][] {
  return times.map((time, index) => [time, values[index] ?? null]);
}

/** The numeric half of a `[time, value]` tooltip entry. */
function numberAt(entry: TooltipEntry | undefined): number {
  if (!entry) return 0;
  if (Array.isArray(entry.value)) return entry.value[1] ?? 0;
  return entry.value ?? 0;
}

function usd(value: number): string {
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

function formatStamp(value: number | undefined): string {
  if (value === undefined) return '';
  return new Date(value).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
