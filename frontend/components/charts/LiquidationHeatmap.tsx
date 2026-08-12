'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle, Check, Info, Palette as PaletteIcon, RefreshCw } from 'lucide-react';

import { useLiquidationMap } from '@/hooks/queries';

/**
 * Coinglass-style liquidation heatmap.
 *
 * Every colour and geometry value here is resolved from the design tokens at
 * runtime rather than passed to ECharts as `var(--token)`: the canvas renderer
 * hands colour strings straight to the 2D context, which silently ignores CSS
 * custom properties, so `var(...)` in a chart option renders as nothing.
 */

/**
 * Pinned to BTC. The backend model is symbol-agnostic, but BTC is the only
 * market deep enough for the open-interest and long/short statistics the model
 * consumes to be meaningful at every interval.
 */
const DEFAULT_SYMBOL = 'BTCUSDT';

const INTERVALS = [
  { value: '4h', label: '4H' },
  { value: '1d', label: '1D' },
  { value: '1w', label: '1W' },
] as const;

type Interval = (typeof INTERVALS)[number]['value'];

/** The subset of an ECharts tooltip callback payload this chart reads. */
interface TooltipParams {
  seriesType?: string;
  value?: unknown;
}

/** Design tokens the chart needs as literal colours. */
const TOKENS = [
  '--fg',
  '--fg-muted',
  '--fg-subtle',
  '--surface',
  '--surface-2',
  '--border',
  '--border-strong',
  '--up',
  '--down',
  '--up-bg',
  '--down-bg',
  '--heat-seq-1',
  '--heat-seq-2',
  '--heat-seq-3',
  '--heat-seq-4',
  '--warn',
] as const;

type Token = (typeof TOKENS)[number];
type Palette = Record<Token, string>;

/** Values from globals.css, used until the document is available. */
const FALLBACK: Palette = {
  '--fg': '#e8e8ea',
  '--fg-muted': '#9a9aa3',
  '--fg-subtle': '#6b6b74',
  '--surface': '#111114',
  '--surface-2': '#17171b',
  '--border': '#232328',
  '--border-strong': '#34343b',
  '--up': '#22c55e',
  '--down': '#ef4444',
  '--up-bg': 'rgba(34, 197, 94, 0.12)',
  '--down-bg': 'rgba(239, 68, 68, 0.12)',
  '--heat-seq-1': '#1f3b6e',
  '--heat-seq-2': '#285099',
  '--heat-seq-3': '#2f63c3',
  '--heat-seq-4': '#4788ff',
  '--warn': '#f59e0b',
};

function readPalette(): Palette {
  if (typeof window === 'undefined') return FALLBACK;
  const computed = getComputedStyle(document.documentElement);
  const palette = { ...FALLBACK };
  for (const token of TOKENS) {
    const value = computed.getPropertyValue(token).trim();
    if (value) palette[token] = value;
  }
  return palette;
}

/** `#rrggbb` → `[r, g, b]`. */
function parseHex(hex: string): [number, number, number] {
  const clean = hex.replace('#', '');
  const full =
    clean.length === 3
      ? clean
          .split('')
          .map((c) => c + c)
          .join('')
      : clean;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

/**
 * Selectable heat ramps.
 *
 * Only the liquidity layer is themeable — the candles stay on `--up`/`--down`,
 * because green-up/red-down is read pre-attentively and re-colouring it would
 * cost far more than the heat layer gains. Every ramp therefore has to stay
 * legible *underneath* those two hues, which rules out green- and red-dominant
 * bases; the contrasting top stop is the one place a warm hue is affordable,
 * since only a handful of magnet levels ever reach it.
 *
 * Each scheme follows the default's two-colour shape: the first four stops are
 * one hue climbing from near-black to bright — wide enough apart that "faint"
 * and "strong" never look like the same shade — and the fifth is a deliberately
 * contrasting hue that fires only at the saturating end. Reading the map is
 * then a two-step question ("is this the base hue or the accent?") rather than
 * a judgement over a continuous gradient.
 *
 * `null` stops mean "resolve from the design tokens" — the default scheme
 * follows the active theme instead of pinning hex values.
 */
const SCHEMES = [
  { value: 'blue', label: 'Blue', stops: null },
  {
    value: 'violet',
    label: 'Violet',
    stops: ['#1b0a4a', '#3a1a9e', '#6a3aee', '#b79bff', '#22d3ee'],
  },
  { value: 'teal', label: 'Teal', stops: ['#052a34', '#08606b', '#0fa89f', '#7cf0dc', '#f0abfc'] },
  {
    value: 'magenta',
    label: 'Magenta',
    stops: ['#2c0433', '#6c0d78', '#bd1cb0', '#f5a8ff', '#fde047'],
  },
  {
    value: 'amber',
    label: 'Amber',
    stops: ['#2b1a02', '#63400a', '#ad7a0c', '#fbc02d', '#60a5fa'],
  },
  { value: 'mono', label: 'Mono', stops: ['#1a1a20', '#41414b', '#7b7b88', '#c9c9d4', '#ffffff'] },
] as const;

type SchemeValue = (typeof SCHEMES)[number]['value'];

const DEFAULT_SCHEME: SchemeValue = 'blue';
const SCHEME_STORAGE_KEY = 'liq-heatmap-scheme';

function isSchemeValue(value: string | null): value is SchemeValue {
  return SCHEMES.some((scheme) => scheme.value === value);
}

/** The five ramp stops for a scheme, falling back to the theme tokens. */
function schemeStops(scheme: SchemeValue, palette: Palette): string[] {
  const stops = SCHEMES.find((entry) => entry.value === scheme)?.stops;
  if (stops) return [...stops];
  return [
    palette['--heat-seq-1'],
    palette['--heat-seq-2'],
    palette['--heat-seq-3'],
    palette['--heat-seq-4'],
    palette['--warn'],
  ];
}

/**
 * Build a colour lookup for the heat ramp.
 *
 * Liquidity clusters are extremely skewed — a handful of magnet levels dwarf
 * everything else — so intensity is gamma-corrected before it reaches the ramp,
 * otherwise all but the top few cells collapse into the darkest stop.
 *
 * Hue and opacity are then pulled apart on purpose: hue climbs quickly so the
 * mid range separates, while alpha climbs on a steep curve so weak levels sink
 * into the background instead of washing the whole canvas blue. Only the real
 * magnet levels reach full opacity.
 */
function buildRamp(rampStops: string[], steps = 96): string[] {
  const stops = rampStops.map(parseHex);

  return Array.from({ length: steps }, (_, index) => {
    const t = index / (steps - 1);
    const scaled = t * (stops.length - 1);
    const lower = Math.min(Math.floor(scaled), stops.length - 2);
    const local = scaled - lower;

    const [r, g, b] = stops[lower].map((channel, axis) =>
      Math.round(channel + (stops[lower + 1][axis] - channel) * local)
    );
    const alpha = 0.03 + 0.97 * Math.pow(t, ALPHA_CURVE);
    return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
  });
}

/** Gamma applied to `value / max` before the ramp lookup. */
const GAMMA = 0.5;
/** Exponent on the opacity ramp; > 1 keeps faint cells close to the background. */
const ALPHA_CURVE = 2.1;
/** Percentile of cell values treated as full heat; anything above it saturates. */
const INTENSITY_CLIP = 0.98;

function compactUsd(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(0)}K`;
  return `$${value.toFixed(0)}`;
}

interface LiquidationHeatmapProps {
  /** Overrides the pinned BTC market. */
  symbol?: string;
  className?: string;
}

export default function LiquidationHeatmap({
  symbol = DEFAULT_SYMBOL,
  className = '',
}: LiquidationHeatmapProps) {
  const [interval, setInterval] = useState<Interval>('4h');
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  const [scheme, setScheme] = useState<SchemeValue>(DEFAULT_SCHEME);
  const [schemeOpen, setSchemeOpen] = useState(false);
  const schemeRef = useRef<HTMLDivElement>(null);

  // Tokens live on the document, so they can only be read after hydration; the
  // stored scheme is read in the same pass to keep the first render (and the
  // server's) on the deterministic default.
  useEffect(() => {
    setPalette(readPalette());
    const stored = window.localStorage.getItem(SCHEME_STORAGE_KEY);
    if (isSchemeValue(stored)) setScheme(stored);
  }, []);

  // Dismiss the scheme popover on an outside click or Escape.
  useEffect(() => {
    if (!schemeOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!schemeRef.current?.contains(event.target as Node)) setSchemeOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSchemeOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [schemeOpen]);

  const selectScheme = (value: SchemeValue) => {
    setScheme(value);
    setSchemeOpen(false);
    window.localStorage.setItem(SCHEME_STORAGE_KEY, value);
  };

  const { data, isLoading, isFetching, isError, error, refetch } = useLiquidationMap(
    symbol,
    interval
  );

  const ramp = useMemo(() => buildRamp(schemeStops(scheme, palette)), [scheme, palette]);

  const option = useMemo(() => {
    if (!data?.candles.length) return undefined;

    const { candles, cells, price_min, bin_size, interval_ms } = data;
    const firstTime = candles[0].time * 1000;
    const step = interval_ms || 3_600_000;

    // Custom-series item: [timeMs, binCentrePrice, total, longUsd, shortUsd].
    const heatData = cells.map(([column, bin, longUsd, shortUsd]) => [
      firstTime + column * step,
      price_min + (bin + 0.5) * bin_size,
      longUsd + shortUsd,
      longUsd,
      shortUsd,
    ]);

    const candleData = candles.map((candle) => [
      candle.time * 1000,
      candle.open,
      candle.close,
      candle.low,
      candle.high,
    ]);

    // Normalise against a high percentile rather than the outright maximum. A
    // single untouched level far from price can be an order of magnitude above
    // everything else, and scaling to it flattens the whole map into one shade;
    // clipping instead lets the handful of genuine magnet levels saturate.
    const sorted = cells.map(([, , longUsd, shortUsd]) => longUsd + shortUsd).sort((a, b) => a - b);
    const peak = sorted[Math.floor((sorted.length - 1) * INTENSITY_CLIP)] || 1;
    const rampTop = ramp.length - 1;

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 8, right: 68, top: 12, bottom: 24, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        borderWidth: 1,
        padding: [6, 9],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (raw: TooltipParams | TooltipParams[]) => {
          // ECharts passes an array when several items sit under the cursor,
          // and omits `value` entirely for non-data targets — neither shape is
          // worth a tooltip, but both reach this callback.
          const params = Array.isArray(raw) ? raw[0] : raw;
          if (!Array.isArray(params?.value)) return '';
          const value = params.value as number[];

          const stamp = new Date(value[0]).toLocaleString('en-GB', {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
          });

          if (params.seriesType === 'candlestick') {
            return [
              `<div style="color:${palette['--fg-muted']}">${stamp}</div>`,
              `O ${value[1]}&nbsp;&nbsp;H ${value[4]}`,
              `L ${value[3]}&nbsp;&nbsp;C ${value[2]}`,
            ].join('<br/>');
          }

          const [, price, total, longUsd, shortUsd] = value;
          return [
            `<div style="color:${palette['--fg-muted']}">${stamp}</div>`,
            `<b>$${price.toLocaleString('en-US', { maximumFractionDigits: 2 })}</b>`,
            `Est. liquidity <b>${compactUsd(total)}</b>`,
            `<span style="color:${palette['--down']}">Long ${compactUsd(longUsd)}</span>` +
              `&nbsp;&nbsp;<span style="color:${palette['--up']}">Short ${compactUsd(shortUsd)}</span>`,
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
          lineStyle: { color: palette['--border-strong'] },
          label: { backgroundColor: palette['--surface-2'], color: palette['--fg-muted'] },
        },
      },
      yAxis: {
        type: 'value',
        scale: true,
        position: 'right',
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
          data: heatData,
          z: 1,
          renderItem: (
            _params: unknown,
            api: {
              value: (dim: number) => number;
              coord: (point: number[]) => number[];
            }
          ) => {
            const time = api.value(0);
            const price = api.value(1);

            const topLeft = api.coord([time - step / 2, price + bin_size / 2]);
            const bottomRight = api.coord([time + step / 2, price - bin_size / 2]);

            const intensity = Math.pow(Math.min(api.value(2) / peak, 1), GAMMA);

            return {
              type: 'rect',
              shape: {
                x: topLeft[0],
                y: topLeft[1],
                // +0.6px closes the seams between neighbouring cells.
                width: bottomRight[0] - topLeft[0] + 0.6,
                height: bottomRight[1] - topLeft[1] + 0.6,
              },
              style: { fill: ramp[Math.round(intensity * rampTop)] },
            };
          },
        },
        {
          name: 'Price',
          type: 'candlestick',
          data: candleData,
          z: 3,
          itemStyle: {
            // Solid bodies, not the hollow style used elsewhere: over a heatmap
            // an outline-only candle disappears into the cells behind it.
            color: palette['--up'],
            color0: palette['--down'],
            borderColor: palette['--up'],
            borderColor0: palette['--down'],
            borderWidth: 1,
          },
        },
      ],
    };
  }, [data, palette, ramp]);

  const lastPrice = data?.candles.at(-1)?.close;

  return (
    <div className={`flex flex-col w-full h-full bg-bg ${className}`}>
      {/* Toolbar */}
      <div className="shrink-0 flex items-center justify-between gap-3 px-3 h-10 border-b border-line bg-surface">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base font-semibold text-fg truncate">Liquidation Heatmap</span>
          <span className="px-1.5 py-0.5 rounded text-2xs font-mono bg-surface-2 text-fg-muted">
            {data?.symbol ?? symbol}
          </span>
          {lastPrice !== undefined && (
            <span className="text-xs font-mono tabnum text-fg-muted">
              ${lastPrice.toLocaleString('en-US', { maximumFractionDigits: 2 })}
            </span>
          )}
          <span
            className="text-fg-subtle"
            title="Estimated liquidation levels modelled from OKX open interest, volume and the long/short ratio — not observed liquidations."
          >
            <Info className="w-3 h-3" />
          </span>
          {data !== undefined && data.stats_from_column > 0 && (
            <span
              className="px-1.5 py-0.5 rounded text-2xs bg-surface-2 text-fg-subtle"
              title={`The oldest ${data.stats_from_column} columns predate OKX's open-interest and long/short history — modelled from volume alone with a neutral split.`}
            >
              partial
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Intensity legend — doubles as the ramp colour picker. */}
          <div ref={schemeRef} className="relative">
            <button
              onClick={() => setSchemeOpen((open) => !open)}
              title="Liquidation heat colours"
              aria-haspopup="menu"
              aria-expanded={schemeOpen}
              className={`flex items-center gap-1.5 px-1.5 py-1 rounded border transition-colors ${
                schemeOpen
                  ? 'border-line-strong text-fg'
                  : 'border-transparent text-fg-subtle hover:border-line hover:text-fg-muted'
              }`}
            >
              <PaletteIcon className="w-3 h-3" />
              <span className="hidden sm:inline text-2xs">low</span>
              <span
                className="h-1.5 w-16 rounded-sm"
                style={{ background: `linear-gradient(90deg, ${ramp.join(', ')})` }}
              />
              <span className="hidden sm:inline text-2xs">high</span>
            </button>

            {schemeOpen && (
              <div
                role="menu"
                className="absolute right-0 top-full mt-1 z-20 w-44 p-1 rounded-md border border-line bg-surface shadow-lg"
              >
                <div className="px-1.5 py-1 text-2xs text-fg-subtle">Liquidation colours</div>
                {SCHEMES.map((entry) => {
                  // Solid stops, not the alpha-weighted ramp: the swatch is
                  // there to tell the schemes apart, and the real ramp's faint
                  // low end reads as empty at this size.
                  const preview = schemeStops(entry.value, palette);
                  const active = entry.value === scheme;
                  return (
                    <button
                      key={entry.value}
                      role="menuitemradio"
                      aria-checked={active}
                      onClick={() => selectScheme(entry.value)}
                      className={`w-full flex items-center gap-2 px-1.5 py-1 rounded text-xs transition-colors ${
                        active ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:bg-surface-2'
                      }`}
                    >
                      <span
                        className="h-3 w-10 shrink-0 rounded-sm border border-line"
                        style={{ background: `linear-gradient(90deg, ${preview.join(', ')})` }}
                      />
                      <span className="flex-1 text-left">{entry.label}</span>
                      {active && <Check className="w-3 h-3 shrink-0" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="flex gap-0.5">
            {INTERVALS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setInterval(value)}
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
              {error instanceof Error ? error.message : 'Could not load the liquidation map.'}
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
              No market data for {symbol} on OKX perpetuals.
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
