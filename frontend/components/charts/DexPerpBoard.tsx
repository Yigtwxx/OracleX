'use client';

import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

import { useDexPerps } from '@/hooks/queries';
import type { DexPerpPanel, DexPerpVenue, DexPerpsBoard } from '@/lib/api';
import { compactUsd, FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';
import { logFloor, rampColors, shareOfTotal, TOP_N, topVenues } from '@/lib/dex-perps';

/**
 * Which on-chain venue carries the leverage.
 *
 * The rest of this page models where the book sits and how big it is; none of
 * it says whose book. On-chain venues are the half of that answer that can be
 * checked rather than taken on trust — a perpetual DEX publishes its open
 * interest, a centralised one reports it.
 *
 * Three panels, one switch. They draw three different quantities and are three
 * independent rankings — a venue can lead one and be absent from another — so
 * they are never joined into a table, and each names its own provider. The
 * Linear/Log switch is shared because the panels answer one question about
 * three quantities; three independently scaled axes would invite a comparison
 * between them that is not valid.
 *
 * Log is the default: the leading venue holds roughly an order of magnitude
 * more open interest than the second, and on a linear axis everything below it
 * is a sliver.
 */

// `provider` is fixed per panel rather than read off `sources`: the backend
// overwrites `sources[panel]` with the literal `unavailable` on failure, which
// is exactly the moment the unavailable message needs to name who failed.
const PANELS: { key: DexPerpPanel; title: string; hint: string; provider: string }[] = [
  {
    key: 'open_interest',
    title: 'Open Interest',
    hint: 'Positions open right now, in USD.',
    provider: 'DefiLlama',
  },
  {
    key: 'volume_24h',
    title: 'Volume (24h)',
    hint: 'Perpetual volume over the last 24 hours, converted from BTC.',
    provider: 'CoinGecko',
  },
  {
    key: 'tvl',
    title: 'Total Value Locked',
    hint: 'Collateral and liquidity held by the venue.',
    provider: 'DefiLlama',
  },
];

const PROVIDER_LABEL: Record<string, string> = {
  defillama: 'DefiLlama',
  coingecko: 'CoinGecko',
};

/**
 * The ramp every panel's bars walk, leader first.
 *
 * The board's own venue tokens rather than the generic `--chart-*` set: these
 * are the two charts in the terminal that colour by venue, so they read as a
 * family. Not the same mapping though — the open-interest board assigns a token
 * per venue, this one interpolates across rank — so the resemblance is in the
 * hues, not in what a given colour means.
 *
 * `--oi-total` is deliberately absent despite sitting between these three in
 * the palette: globals.css reserves it for the aggregate series, and it was
 * kept clear of the venue bands on purpose. A mid-ranked DEX painted in the
 * aggregate's blue would undo that on the board next door.
 */
const BAR_RAMP = ['--oi-venue-1', '--oi-venue-2', '--oi-venue-3'] as const;

/** Bar-tip venue mark, in pixels. Sized to clear the 14px bar it sits on. */
const LOGO_SIZE = 14;

type Scale = 'linear' | 'log';

interface DexPerpBoardProps {
  className?: string;
}

export default function DexPerpBoard({ className = '' }: DexPerpBoardProps) {
  const [scale, setScale] = useState<Scale>('log');
  const [palette, setPalette] = useState<Palette>(FALLBACK);

  // Tokens live on the document, so they can only be read after hydration —
  // the canvas renderer is handed literal colours and ignores `var(--token)`.
  useEffect(() => {
    setPalette(readPalette());
  }, []);

  const { data, isLoading, isFetching, isError, refetch } = useDexPerps();

  return (
    <div className={`h-full flex flex-col ${className}`}>
      <div className="h-9 shrink-0 border-b border-line flex items-center gap-3 px-4">
        <span className="text-sm text-fg">DEX Perps</span>
        <div className="flex gap-0.5 rounded-md bg-surface-2 p-0.5">
          {(['linear', 'log'] as Scale[]).map((option) => (
            <button
              key={option}
              onClick={() => setScale(option)}
              aria-pressed={scale === option}
              className={`px-2 py-0.5 rounded text-2xs capitalize transition-colors ${
                scale === option ? 'bg-surface text-fg' : 'text-fg-muted hover:text-fg'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {isError && data && (
            // The backend never got to say the board is stale — a dead
            // connection just stops answering, and `placeholderData` keeps the
            // last payload on screen with `stale: false` on every panel. This
            // is the frontend's own contradiction of that silence.
            <span className="flex items-center gap-1 text-2xs text-warn">
              <AlertTriangle className="w-3 h-3" />
              Last board received — not current
            </span>
          )}
          <button
            onClick={() => refetch()}
            className="text-fg-muted hover:text-fg transition-colors"
            aria-label="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-3">
        {isError && !data ? (
          <PanelMessage
            icon={<AlertTriangle className="w-4 h-4" />}
            text="The board could not be loaded."
          />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 h-full">
            {PANELS.map((panel) => (
              <Panel
                key={panel.key}
                panel={panel}
                board={data}
                scale={scale}
                palette={palette}
                isLoading={isLoading}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Panel({
  panel,
  board,
  scale,
  palette,
  isLoading,
}: {
  panel: (typeof PANELS)[number];
  board: DexPerpsBoard | undefined;
  scale: Scale;
  palette: Palette;
  isLoading: boolean;
}) {
  // Memoized rather than a plain `?? []`: an inline fallback is a fresh array
  // every render, which would defeat the `shown` memo below on every render.
  const rows: DexPerpVenue[] = useMemo(() => board?.[panel.key] ?? [], [board, panel.key]);
  const source = board?.sources?.[panel.key];
  const stale = board?.stale?.[panel.key] ?? false;
  const shown = useMemo(() => topVenues(rows), [rows]);

  const option = useMemo(() => {
    if (shown.length === 0) return undefined;
    // Drawn bottom-up: ECharts stacks a category axis from the origin, so the
    // leader would otherwise sit at the foot of the panel.
    const colors = rampColors(
      shown.length,
      BAR_RAMP.map((token) => palette[token])
    );
    // Share is computed against `shown` (rank order) before the reverse below,
    // so index i still lines up with colors[i].
    const shares = shareOfTotal(shown);
    // Paired with its colour and share before reversing: both are indexed by
    // rank, and reversing the rows first would paint the tail's shade and
    // share onto the leader.
    const ordered = shown
      .map((row, rank) => ({ row, color: colors[rank], share: shares[rank] }))
      .reverse();
    return {
      backgroundColor: 'transparent',
      grid: { left: 4, right: 76, top: 8, bottom: 24, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: palette['--surface'],
        borderWidth: 0,
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (entry: {
          name: string;
          value: number;
          data: { share: number; change: number | null; chains: string[] };
        }) => {
          const { share, change, chains } = entry.data;
          const lines = [
            `${entry.name}<br/>${compactUsd(entry.value)}`,
            `${(share * 100).toFixed(1)}% of shown`,
          ];
          if (change !== null) {
            const changeColor = change >= 0 ? palette['--up'] : palette['--down'];
            lines.push(
              `<span style="color:${changeColor}">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</span>`
            );
          }
          if (chains.length > 0) {
            lines.push(chains.join(', '));
          }
          return lines.join('<br/>');
        },
      },
      xAxis: {
        type: scale === 'log' ? 'log' : 'value',
        min: scale === 'log' ? logFloor(shown) : 0,
        axisLabel: {
          color: palette['--fg-muted'],
          fontSize: 10,
          formatter: (value: number) => compactUsd(value),
        },
        splitLine: { lineStyle: { color: palette['--border'] } },
      },
      yAxis: {
        type: 'category',
        data: ordered.map(({ row }) => row.name),
        axisLabel: { color: palette['--fg-muted'], fontSize: 10 },
        axisTick: { show: false },
        axisLine: { show: false },
      },
      series: [
        {
          type: 'bar',
          // Per-item rather than per-series: each bar carries its own colour off
          // the ramp, and its own label because the venue's mark is drawn into
          // the label rather than beside the axis. `share`/`change`/`chains`
          // ride along unused by the renderer so the tooltip formatter above
          // can read them straight off `entry.data`.
          data: ordered.map(({ row, color, share }) => ({
            value: row.value_usd,
            share,
            change: row.change_1d_pct,
            chains: row.chains,
            itemStyle: { color, borderRadius: [0, 2, 2, 0] },
            label: {
              // A venue absent from both providers' icon sets gets the figure
              // alone. An empty image box would read as a failed load.
              formatter: row.logo
                ? `{logo|}{value|${compactUsd(row.value_usd)}}`
                : `{value|${compactUsd(row.value_usd)}}`,
              rich: {
                logo: {
                  width: LOGO_SIZE,
                  height: LOGO_SIZE,
                  // No borderRadius: zrender only rounds a rich block's
                  // background when it is a plain colour or gradient, so on an
                  // image background the property is silently inert.
                  backgroundColor: { image: row.logo },
                  verticalAlign: 'middle',
                },
                value: {
                  fontSize: 10,
                  color: palette['--fg-muted'],
                  padding: [0, 0, 0, row.logo ? 5 : 0],
                  verticalAlign: 'middle',
                },
              },
            },
          })),
          barMaxWidth: 14,
          label: { show: true, position: 'right', distance: 6 },
        },
      ],
    };
  }, [shown, scale, palette]);

  return (
    <div className="flex flex-col min-h-[280px] rounded-lg border border-line bg-surface">
      <div className="shrink-0 px-3 py-2 border-b border-line">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-fg">{panel.title}</span>
          {rows.length > 0 && (
            // The cut is named rather than implied: a top-15 that does not say
            // it is a top-15 reads as the whole market.
            <span className="text-2xs text-fg-subtle">
              Top {Math.min(TOP_N, rows.length)} of {rows.length}
            </span>
          )}
          {stale && <span className="text-2xs text-warn">replaying last good data</span>}
        </div>
        <p className="text-2xs text-fg-subtle mt-0.5">
          {panel.hint}
          {source && source !== 'unavailable' && ` · ${PROVIDER_LABEL[source] ?? source}`}
        </p>
      </div>

      <div className="flex-1 min-h-0 p-1">
        {isLoading && !board ? (
          <PanelMessage text="Loading…" />
        ) : source === 'unavailable' ? (
          // Named, not blank: an empty axis reads as a market with nothing in
          // it, which is a different claim from a provider that did not answer.
          <PanelMessage
            icon={<AlertTriangle className="w-4 h-4" />}
            text={`${panel.provider} unavailable — no figures for this panel right now.`}
          />
        ) : option ? (
          <ReactECharts
            option={option}
            style={{ height: '100%', width: '100%' }}
            notMerge
            lazyUpdate
          />
        ) : (
          <PanelMessage text="No venues reported." />
        )}
      </div>
    </div>
  );
}

function PanelMessage({ icon, text }: { icon?: React.ReactNode; text: string }) {
  return (
    <div className="h-full flex items-center justify-center gap-2 text-2xs text-fg-muted">
      {icon}
      <span>{text}</span>
    </div>
  );
}
