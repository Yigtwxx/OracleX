'use client';

import ReactECharts from 'echarts-for-react';
import { useEffect, useMemo, useState } from 'react';

import { formatCompact, formatPercent } from '@/lib/bist-format';
import { OTHER_KEY, frontShare, type ExpiryStack } from '@/lib/bist-viop';
import { FALLBACK, readPalette, type Palette, type Token } from '@/lib/chart-palette';

interface ViopExpiryStackProps {
  stacks: ExpiryStack[];
  /** The underlyings drawn as their own band, in the order they are given. */
  keys: string[];
  height?: number;
}

/**
 * How the book is spread across expiries, and who is in each one.
 *
 * This is the panel that dates the board. Open interest of two million is the
 * same figure whether it sits almost entirely in the front month — a market
 * that has not rolled, whose positions are about to be closed or carried — or
 * spread down the strip, which is a market that already has. The table sorts by
 * size and cannot show the difference; the two boards look identical in every
 * column.
 *
 * Reading it against the quadrant panel is where it earns its place. Open
 * interest rising while the front month empties is not new risk, it is the
 * roll: the same positions moved one contract to the right. A build that shows
 * up in the back month while the front holds is.
 *
 * Colour is identity here — which underlying, not what happened to it — and
 * that is the one categorical use the codebase's palette rule allows. The
 * direction colours are deliberately absent so the two panels beside this one
 * keep their meaning.
 */
export default function ViopExpiryStack({ stacks, keys, height = 240 }: ViopExpiryStackProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const front = useMemo(() => frontShare(stacks), [stacks]);

  const option = useMemo(() => {
    // `Diğer` is drawn last and in the neutral border colour, so the named
    // bands read as the subject and the remainder as the ground behind them.
    const bands = [...keys, OTHER_KEY];

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
      legend: {
        top: 0,
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { color: palette['--fg-subtle'], fontSize: 10 },
        icon: 'roundRect',
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        valueFormatter: (value: number) => formatCompact(value, 1),
      },
      xAxis: {
        type: 'category',
        data: stacks.map((stack) => stack.label),
        axisLine: { lineStyle: { color: palette['--border'] } },
        axisTick: { show: false },
        axisLabel: { color: palette['--fg-subtle'], fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: palette['--fg-subtle'],
          fontSize: 10,
          formatter: (value: number) => formatCompact(value, 0),
        },
        splitLine: { lineStyle: { color: palette['--border'], opacity: 0.35 } },
      },
      series: bands.map((band, index) => ({
        name: band,
        type: 'bar',
        stack: 'oi',
        barMaxWidth: 44,
        itemStyle: { color: palette[bandToken(band, index)] },
        // A band that is zero everywhere still holds a legend entry, so a name
        // the reader picked out of the bar chart does not silently vanish here.
        data: stacks.map((stack) => stack.byUnderlying[band] ?? 0),
      })),
    };
  }, [stacks, keys, palette]);

  if (stacks.length === 0) {
    return (
      <p
        style={{ height }}
        className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
      >
        Vadesi okunabilen ve açık pozisyon yayımlayan sözleşme yok.
      </p>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <p className="sr-only">
        Açık pozisyonun {stacks.length} vadeye dağılımı, en yakın vadeden en uzağa.
      </p>

      <ReactECharts
        option={option}
        notMerge
        opts={{ renderer: 'canvas' }}
        style={{ height, width: '100%' }}
      />

      <div className="flex shrink-0 items-baseline justify-between gap-3 border-t border-line px-3 py-1.5">
        <span className="text-2xs text-fg-muted">
          {/* The reading, stated rather than left for the reader to estimate off
              the bars: it is the one figure here that dates the whole board. */}
          Açık pozisyonun {formatPercent(front, 0)}&apos;i en yakın vadede
        </span>
        <span className="tabnum shrink-0 text-2xs text-fg-subtle">{stacks[0].label}</span>
      </div>
    </div>
  );
}

/**
 * A band's colour.
 *
 * The `--oi-*` tokens rather than the heat ramp: those are identity colours,
 * already used for the venue split on the crypto realm's open-interest board,
 * and a sequential ramp here would imply an order between underlyings that does
 * not exist. Past the fourth name every band shares the neutral colour, which
 * is honest — the legend can carry four names and a reader cannot tell a fifth
 * hue apart from the third anyway.
 */
function bandToken(band: string, index: number): Token {
  if (band === OTHER_KEY) return '--border-strong';
  const tokens: Token[] = ['--oi-total', '--oi-venue-1', '--oi-venue-2', '--oi-venue-3'];
  return tokens[index] ?? '--border-strong';
}
