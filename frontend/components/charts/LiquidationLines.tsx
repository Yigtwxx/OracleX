'use client';

import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle, Circle, Info, RefreshCw } from 'lucide-react';

import { useLiquidationLines } from '@/hooks/queries';
import { LIQUIDATION_EXCHANGES, LIQUIDATION_SYMBOLS, type LiquidationExchange } from '@/lib/api';
import { compactUsd, FALLBACK, parseHex, readPalette, type Palette } from '@/lib/chart-palette';
import {
  BIN,
  bubbleRadius,
  BUBBLE_LIMIT,
  BUCKETS,
  END,
  LEVERAGE,
  leverageBucket,
  lineAlpha,
  maxNotional,
  NOTIONAL,
  SIDE,
  START,
  filterLines,
  topByNotional,
  type LeverageBucket,
} from '@/lib/liquidation-lines';

/**
 * Coinglass-style liquidation *levels*, drawn as spans.
 *
 * The sibling heatmap answers "where is the liquidity"; this answers "how long
 * has it been there, and at what leverage". Same backend model, same price
 * grid — the two tabs are deliberately pinned to one geometry so switching
 * between them never moves the y-axis.
 */

/**
 * Candle interval, which is the control the reference chart exposes and the
 * one that actually decides what the view resolves.
 *
 * The window is a consequence rather than a setting: at a fixed bar count a
 * finer interval buys detail and spends reach, so naming the interval says
 * more than naming the duration would. The resulting span is reported next to
 * the level count so nothing has to be inferred.
 *
 * Every entry stays inside OKX's aggregate-statistics history at `COLUMNS`
 * bars — the longest, 4H, reaches 30 days against the 1D series' 180. A finer
 * interval reaching further would quietly fall back to volume-only columns.
 */
const INTERVALS = [
  { value: '1m', label: '1m' },
  { value: '3m', label: '3m' },
  { value: '5m', label: '5m' },
  { value: '15m', label: '15m' },
  { value: '1h', label: '1H' },
  { value: '4h', label: '4H' },
] as const;

type IntervalValue = (typeof INTERVALS)[number]['value'];

/**
 * Bars drawn per view.
 *
 * 240 plus the model's 60 warm-up columns is exactly the 300 rows OKX serves in
 * one candle page. Asking for more would cost a second request per refresh;
 * asking for less would leave reach on the table, and reach is the scarce half
 * of the trade at the fine intervals.
 */
const COLUMNS = 240;

const DEFAULT_SYMBOL = LIQUIDATION_SYMBOLS[0];
/** Fine enough to show intraday structure, long enough to show two days of it. */
const DEFAULT_INTERVAL: IntervalValue = '15m';

/**
 * Hue by leverage, on a separate ramp per side.
 *
 * Leverage is what decides how far a level sits from the price that created it,
 * so a ramp over the tiers is also a ramp over distance — and running the two
 * sides in opposite directions makes the whole chart legible at a glance: cool
 * above price, warm below, saturating as the levels crowd in on it. A single
 * categorical palette cannot do that, and the `--heat-seq-*` ramp the heatmap
 * uses would claim an ordering of *intensity* where this one means risk.
 *
 * The stops are hard-coded, as the heatmap's schemes are, and for the same
 * reason: `--up` green and `--down` red belong to the candles, which are read
 * pre-attentively, so both ramps stay clear of those two hues while still
 * spanning enough spectrum to separate ten tiers.
 */
const SHORT_RAMP = ['#34d399', '#22d3ee', '#3b82f6', '#6366f1'];
const LONG_RAMP = ['#a855f7', '#e879f9', '#f472b6', '#fb923c'];

/** Opacity resolution. Enough steps that the ramp reads continuous. */
const ALPHA_STEPS = 40;

/**
 * Drawn thickness of one span, in pixels.
 *
 * One, not two. At ten tiers the book is dense enough that a thicker span
 * merges with its neighbours into a solid block, and the thing worth seeing —
 * where each level starts and stops — goes with it.
 */
const SPAN_HEIGHT = 1;

/**
 * A bubble's outline is drawn at full opacity regardless of its span's.
 *
 * The spans encode size by opacity; the bubbles encode it by area, and only
 * the heaviest sixty get one at all. Dimming them by the same ramp would say
 * the same thing twice and lose the marks in the field they sit on.
 */
const RING_ALPHA = ALPHA_STEPS - 1;

/** Fill alpha step, low enough that overlapping bubbles stay countable. */
const FILL_ALPHA = 3;

/** Radius from which a bubble is large enough for a centre dot to mean anything. */
const DOT_FROM = 6;
const DOT_RADIUS = 1.5;

const BUCKET_LABELS: Record<LeverageBucket, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

/** A drawn window, in the coarsest unit that still reads as a round number. */
function formatSpan(ms: number): string {
  const hours = ms / 3_600_000;
  if (hours < 1) return `${Math.round(ms / 60_000)}m`;
  if (hours < 48) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}

/** The subset of an ECharts custom-series render API this chart uses. */
interface RenderApi {
  value: (dim: number) => number;
  coord: (point: number[]) => number[];
  size: (range: number[]) => number[];
}

/** The subset of an ECharts tooltip callback payload this chart reads. */
interface TooltipParams {
  seriesType?: string;
  value?: unknown;
}

/** Sample a ramp of hex stops at `t` in [0, 1]. */
function rampAt(stops: string[], t: number): [number, number, number] {
  const scaled = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const lower = Math.min(Math.floor(scaled), stops.length - 2);
  const local = scaled - lower;
  const from = parseHex(stops[lower]);
  const to = parseHex(stops[lower + 1]);
  return [0, 1, 2].map((axis) => Math.round(from[axis] + (to[axis] - from[axis]) * local)) as [
    number,
    number,
    number,
  ];
}

/** The hue one side's tier is drawn in, before opacity. */
export function spanHue(side: number, tierIndex: number, tierCount: number): string {
  const t = tierCount > 1 ? tierIndex / (tierCount - 1) : 0;
  const [r, g, b] = rampAt(side === 0 ? LONG_RAMP : SHORT_RAMP, t);
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * `[side * tierCount + tierIndex][alphaStep]` → an rgba string.
 *
 * Flattened over side and tier so `renderItem` can index it with one value it
 * already carries, rather than doing arithmetic per span on a canvas that draws
 * thousands of them.
 */
function buildSpanColors(tierCount: number): string[][] {
  const colors: string[][] = [];
  for (const side of [0, 1]) {
    for (let tier = 0; tier < tierCount; tier += 1) {
      const t = tierCount > 1 ? tier / (tierCount - 1) : 0;
      const [r, g, b] = rampAt(side === 0 ? LONG_RAMP : SHORT_RAMP, t);
      colors.push(
        Array.from(
          { length: ALPHA_STEPS },
          (_, step) => `rgba(${r}, ${g}, ${b}, ${(step / (ALPHA_STEPS - 1)).toFixed(3)})`
        )
      );
    }
  }
  return colors;
}

interface LiquidationLinesProps {
  className?: string;
}

export default function LiquidationLines({ className = '' }: LiquidationLinesProps) {
  const [symbol, setSymbol] = useState<string>(DEFAULT_SYMBOL);
  // Not `setInterval`: that name shadows the global timer inside the whole
  // component, and the next person to reach for a real one would find this.
  const [interval, selectInterval] = useState<IntervalValue>(DEFAULT_INTERVAL);
  const [venue, setVenue] = useState<LiquidationExchange>('okx');
  const [buckets, setBuckets] = useState<Set<LeverageBucket>>(() => new Set(BUCKETS));
  const [bubbles, setBubbles] = useState(true);
  const [palette, setPalette] = useState<Palette>(FALLBACK);

  // Tokens live on the document, so they can only be read after hydration.
  useEffect(() => {
    setPalette(readPalette());
  }, []);

  const { data, isLoading, isFetching, isError, error, refetch } = useLiquidationLines(
    symbol,
    interval,
    COLUMNS,
    venue
  );

  // Only for the moment before a payload arrives, and for the tooltips — which
  // read wrong if they say OKX while Bybit is selected.
  const venueName = LIQUIDATION_EXCHANGES.find((entry) => entry.value === venue)?.label ?? 'OKX';

  const toggleBucket = (bucket: LeverageBucket) => {
    setBuckets((current) => {
      const next = new Set(current);
      // Never let the last one off: an empty chart reads as a failed load, and
      // the user has no way to tell it apart from one.
      if (next.has(bucket) && next.size > 1) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  };

  const option = useMemo(() => {
    if (!data?.candles.length) return undefined;

    const { candles, lines, price_min, bin_size, interval_ms, leverage_tiers, tier_max } = data;
    const firstTime = candles[0].time * 1000;
    const step = interval_ms || 3_600_000;

    const colors = buildSpanColors(leverage_tiers.length);
    const tierIndex = new Map(leverage_tiers.map((tier, index) => [tier, index]));

    // Scaled to the whole book rather than to the visible slice, so that the
    // leverage filter changes what is drawn and never how large it is drawn.
    const largest = maxNotional(lines);

    // [startMs, endMs, price, colourIndex, alphaStep, leverage, side, notional,
    //  bubbleRadius] — both series share the layout so one tooltip formatter
    // serves them both.
    const toItem = (line: (typeof lines)[number]) => {
      const index = tierIndex.get(line[LEVERAGE]) ?? 0;
      const alpha = lineAlpha(line[NOTIONAL], tier_max[index] || 0);
      return [
        firstTime + line[START] * step,
        firstTime + line[END] * step,
        price_min + (line[BIN] + 0.5) * bin_size,
        line[SIDE] * leverage_tiers.length + index,
        Math.round(alpha * (ALPHA_STEPS - 1)),
        line[LEVERAGE],
        line[SIDE],
        line[NOTIONAL],
        bubbleRadius(line[NOTIONAL], largest),
      ];
    };

    const visibleLines = filterLines(lines, buckets);
    const spanData = visibleLines.map(toItem);
    const bubbleData = bubbles ? topByNotional(visibleLines, BUBBLE_LIMIT).map(toItem) : [];

    const candleData = candles.map((candle) => [
      candle.time * 1000,
      candle.open,
      candle.close,
      candle.low,
      candle.high,
    ]);

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: {
        left: 8,
        right: 6,
        top: 12,
        bottom: 6,
        containLabel: true,
        // `right`/`bottom` are small because `containLabel` already reserves the axis
        // labels; anything more is empty margin outside them. It used to be 68 and
        // 24, which predates `containLabel` and was reserving the same space twice
        // — invisible while the plot was unpainted, an obvious black band around it
        // afterwards. Both charts carry the same numbers on purpose: they share a
        // price grid, and a different margin would move the axis on a tab switch.
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        borderWidth: 1,
        padding: [6, 9],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (raw: TooltipParams | TooltipParams[]) => {
          const params = Array.isArray(raw) ? raw[0] : raw;
          if (!Array.isArray(params?.value)) return '';
          const value = params.value as number[];

          const stamp = (ms: number) =>
            new Date(ms).toLocaleString('en-GB', {
              day: '2-digit',
              month: 'short',
              hour: '2-digit',
              minute: '2-digit',
            });

          if (params.seriesType === 'candlestick') {
            return [
              `<div style="color:${palette['--fg-muted']}">${stamp(value[0])}</div>`,
              `O ${value[1]}&nbsp;&nbsp;H ${value[4]}`,
              `L ${value[3]}&nbsp;&nbsp;C ${value[2]}`,
            ].join('<br/>');
          }

          const [startMs, endMs, price, , , leverage, side, notional] = value;
          const swept = endMs < candles[candles.length - 1].time * 1000;
          // A span clamped to the left edge predates the window, so the model
          // cannot date its origin — say so rather than assert a candle.
          const opened = startMs <= firstTime ? `open since ≤ ${stamp(firstTime)}` : stamp(startMs);

          return [
            `<b>$${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b>`,
            `<span style="color:${side === 0 ? palette['--down'] : palette['--up']}">` +
              `${side === 0 ? 'Long' : 'Short'} ${leverage}x</span>` +
              `&nbsp;&nbsp;<b>${compactUsd(notional)}</b>`,
            `<div style="color:${palette['--fg-muted']}">${opened}</div>`,
            `<div style="color:${palette['--fg-subtle']}">` +
              `${swept ? `swept ${stamp(endMs)}` : 'still standing'}</div>`,
          ].join('<br/>');
        },
      },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { color: palette['--fg-subtle'], fontSize: 10, hideOverlap: true },
        axisPointer: {
          show: true,
          // Above every series. ECharts draws the axis pointer at z 0 by
          // default, which on this chart puts the crosshair and its price
          // label *under* the liquidity cells — the label became unreadable
          // the moment it crossed a bright row, which is exactly where a
          // reader puts it.
          z: 100,
          lineStyle: { color: palette['--border-strong'] },
          label: { backgroundColor: palette['--surface-2'], color: palette['--fg-muted'] },
        },
      },
      yAxis: {
        type: 'value',
        scale: true,
        position: 'right',
        // Pinned to the model's own grid, which is the grid the heatmap tab
        // uses too — that is what keeps the axis still across a tab switch.
        min: data.price_min,
        max: data.price_max,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => value.toLocaleString('en-US', { maximumFractionDigits: 0 }),
        },
        axisPointer: {
          show: true,
          z: 100,
          label: { backgroundColor: palette['--surface-2'], color: palette['--fg-muted'] },
        },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
        { type: 'inside', yAxisIndex: 0, filterMode: 'none', zoomOnMouseWheel: false },
      ],
      series: [
        {
          name: 'Liquidation levels',
          type: 'custom',
          progressive: 4000,
          progressiveThreshold: 2000,
          data: spanData,
          z: 1,
          // A span opened and swept inside the final candle is floored to one
          // column below, which puts its right edge a whole column past the
          // axis. Unclipped it draws into the gutter, and only on the rows that
          // happen to own such a span — the same serrated edge the heatmap had.
          clip: true,
          renderItem: (_params: unknown, api: RenderApi) => {
            const price = api.value(2);
            const left = api.coord([api.value(0), price]);
            const right = api.coord([api.value(1), price]);

            // A level opened and swept inside one candle has zero width in data
            // space. Floor it at one column so the shortest-lived spans — which
            // are the whole 100x band — do not fall below a pixel.
            const columnWidth = api.size([step, 0])[0];
            const width = Math.max(right[0] - left[0], columnWidth);

            return {
              type: 'rect',
              shape: { x: left[0], y: left[1] - SPAN_HEIGHT / 2, width, height: SPAN_HEIGHT },
              style: { fill: colors[api.value(3)][api.value(4)] },
            };
          },
        },
        {
          name: 'Heaviest levels',
          type: 'custom',
          // Sixty items; the spans' progressive rendering would only add a
          // frame boundary here.
          data: bubbleData,
          z: 2,
          // Unlike a one-pixel span, a bubble sitting on the top or bottom of
          // the book reaches well past it and would paint over the axis.
          clip: true,
          renderItem: (_params: unknown, api: RenderApi) => {
            const [cx, cy] = api.coord([api.value(0), api.value(2)]);
            const radius = api.value(8);
            const ramp = colors[api.value(3)];
            const stroke = ramp[RING_ALPHA];

            const ring = {
              type: 'circle',
              shape: { cx, cy, r: radius },
              style: { fill: ramp[FILL_ALPHA], stroke, lineWidth: 1 },
            };

            // Below a few pixels the ring already reads as a dot, and a second
            // shape per item is a cost the dense tail cannot carry.
            if (radius < DOT_FROM) return ring;
            return {
              type: 'group',
              children: [
                ring,
                { type: 'circle', shape: { cx, cy, r: DOT_RADIUS }, style: { fill: stroke } },
              ],
            };
          },
        },
        {
          name: 'Price',
          type: 'candlestick',
          data: candleData,
          z: 3,
          itemStyle: {
            // Solid bodies, as on the heatmap: over a dense field of spans an
            // outline-only candle disappears into what is behind it.
            color: palette['--up'],
            color0: palette['--down'],
            borderColor: palette['--up'],
            borderColor0: palette['--down'],
            borderWidth: 1,
          },
        },
      ],
    };
  }, [data, palette, buckets, bubbles]);

  const lastPrice = data?.candles.at(-1)?.close;
  const visible = data ? filterLines(data.lines, buckets).length : 0;
  // Read off the payload rather than recomputed from a client-side table: the
  // backend clamps the bar count, so this is the window actually drawn.
  const spanLabel = data ? formatSpan(data.interval_ms * data.candles.length) : '';

  return (
    <div className={`flex flex-col w-full h-full bg-bg ${className}`}>
      {/* Toolbar */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-3 h-10 border-b border-line bg-surface overflow-x-auto">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base font-semibold text-fg truncate">Liquidation Levels</span>

          {/* Venue first, and selectable: the whole chart is a model of one
              exchange's book, so which one is not a caption. A level standing on
              Binance says nothing about what is standing on Bybit. */}
          <select
            value={venue}
            onChange={(event) => setVenue(event.target.value as LiquidationExchange)}
            aria-label="Exchange"
            className="px-1.5 py-0.5 rounded text-2xs font-mono bg-surface-2 text-fg-subtle border border-line hover:text-fg"
          >
            {LIQUIDATION_EXCHANGES.map((entry) => (
              <option key={entry.value} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </select>

          <select
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            aria-label="Market"
            className="px-1.5 py-0.5 rounded text-2xs font-mono bg-surface-2 text-fg-muted border border-line hover:text-fg"
          >
            {LIQUIDATION_SYMBOLS.map((entry) => (
              <option key={entry} value={entry}>
                {entry}
              </option>
            ))}
          </select>

          {lastPrice !== undefined && (
            <span className="text-xs font-mono tabnum text-fg-muted">
              ${lastPrice.toLocaleString('en-US', { maximumFractionDigits: 2 })}
            </span>
          )}
          <span
            className="text-fg-subtle"
            title={`Estimated liquidation levels modelled from ${venueName} open interest, volume and the long/short ratio — not observed liquidations. Each span runs from where the level was opened to where price swept it; the bubbles ring the heaviest of them at their origin.`}
          >
            <Info className="w-3 h-3" />
          </span>
          {data !== undefined && data.stats_from_column > 0 && (
            <span
              className="px-1.5 py-0.5 rounded text-2xs bg-surface-2 text-fg-subtle"
              title={`The oldest ${data.stats_from_column} columns predate ${venueName}'s open-interest and long/short history — modelled from volume alone with a neutral split.`}
            >
              partial
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Leverage filter. Client-side: the payload already carries every
              tier, so a toggle never costs a request. */}
          <div className="flex gap-0.5" role="group" aria-label="Leverage bands">
            {BUCKETS.map((bucket) => {
              const active = buckets.has(bucket);
              const tiers = data?.leverage_tiers ?? [];
              const members = tiers
                .map((tier, index) => ({ tier, index }))
                .filter(({ tier }) => leverageBucket(tier) === bucket);
              // Both sides, at the band's midpoint: the swatch has to say which
              // colours the toggle governs, and each band spans two ramps.
              const mid = members.length ? members[Math.floor(members.length / 2)].index : 0;
              const hues = members.length
                ? [spanHue(1, mid, tiers.length), spanHue(0, mid, tiers.length)]
                : ['#7b7b88'];
              return (
                <button
                  key={bucket}
                  role="checkbox"
                  aria-checked={active}
                  onClick={() => toggleBucket(bucket)}
                  title={`${BUCKET_LABELS[bucket]} leverage`}
                  className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-2xs transition-colors ${
                    active
                      ? 'border-line-strong text-fg'
                      : 'border-transparent text-fg-subtle hover:text-fg-muted'
                  }`}
                >
                  <span
                    className="h-2 w-2 rounded-sm shrink-0"
                    style={{
                      background:
                        hues.length > 1 ? `linear-gradient(90deg, ${hues.join(', ')})` : hues[0],
                      opacity: active ? 1 : 0.3,
                    }}
                  />
                  {BUCKET_LABELS[bucket]}
                </button>
              );
            })}
          </div>

          <button
            role="checkbox"
            aria-checked={bubbles}
            onClick={() => setBubbles((on) => !on)}
            title={`Ring the ${BUBBLE_LIMIT} heaviest levels at their origin, sized by notional`}
            className={`flex items-center gap-1 px-1.5 py-0.5 rounded border text-2xs transition-colors ${
              bubbles
                ? 'border-line-strong text-fg'
                : 'border-transparent text-fg-subtle hover:text-fg-muted'
            }`}
          >
            <Circle className={`w-2.5 h-2.5 ${bubbles ? '' : 'opacity-30'}`} />
            Bubbles
          </button>

          <div className="flex gap-0.5" role="group" aria-label="Candle interval">
            {INTERVALS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => selectInterval(value)}
                title={`${label} candles — ${COLUMNS} bars`}
                className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                  interval === value ? 'bg-surface-2 text-fg' : 'text-fg-subtle hover:text-fg-muted'
                }`}
              >
                {label}
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

      {/* Chart */}
      <div className="relative flex-1 min-h-0 w-full">
        {isLoading ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
            <RefreshCw className="w-4 h-4 animate-spin text-fg-muted" />
            <span className="text-sm text-fg-muted">Modelling liquidation levels…</span>
          </div>
        ) : isError ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center">
            <AlertTriangle className="w-4 h-4 text-down" />
            <span className="text-sm text-fg-muted">
              {error instanceof Error ? error.message : 'Could not load the liquidation levels.'}
            </span>
            <button
              onClick={() => refetch()}
              className="mt-1 px-2.5 py-1 rounded-md border border-line text-sm text-fg-muted hover:text-fg"
            >
              Retry
            </button>
          </div>
        ) : !option ? (
          <div className="absolute inset-0 flex items-center justify-center px-6 text-center">
            <span className="text-sm text-fg-muted">
              No market data for {symbol} on {venueName} perpetuals.
            </span>
          </div>
        ) : (
          <>
            <ReactECharts
              option={option}
              style={{ height: '100%', width: '100%' }}
              opts={{ renderer: 'canvas' }}
              notMerge
            />
            <span // Clears the time axis, which now sits closer to the frame than it
              // used to: the count would otherwise print over the first label.
              className="absolute bottom-6 left-2 text-2xs text-fg-subtle tabnum pointer-events-none"
            >
              {visible.toLocaleString('en-US')} levels
              {spanLabel && ` · ${spanLabel}`}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
