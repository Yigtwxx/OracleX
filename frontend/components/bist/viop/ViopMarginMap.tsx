'use client';

import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';

import type { BistViopMapResponse } from '@/lib/bist-api';
import { formatCompact, formatCompactTry, formatTry } from '@/lib/bist-format';
import { buildRamp, heatCeiling, rampIndex } from '@/lib/heat-ramp';
import { binPrices, pointOfControl, valueArea } from '@/lib/viop-map';
import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';

/** The subset of an ECharts custom-series render API this chart uses. */
interface RenderApi {
  value: (dim: number) => number;
  coord: (point: number[]) => number[];
  size: (range: number[]) => number[];
}

interface TooltipParams {
  seriesType?: string;
  seriesName?: string;
  value?: unknown;
}

interface ViopMarginMapProps {
  data: BistViopMapResponse;
  /** Draw the spot volume profile as a second grid on the right. */
  showProfile?: boolean;
  height?: number;
}

/**
 * The standing book as a density field, drawn under the spot candles.
 *
 * **A field, not a set of bars.** Every session contributes a full snapshot of
 * every level still standing, so a level that survives paints the same row over
 * and over and reads as a streak running left to right — and the session price
 * finally trades through it is that streak stopping dead. The first version drew
 * one rectangle per level from the day it opened to the day it was swept: the
 * same information, and an unreadable barcode at six months.
 *
 * **One ramp, not two hues.** Intensity is `long + short`, through a single
 * sequential ramp. A bin holds one side or the other — a long's band sits below
 * the price that opened it and a short's above, so the two only meet after price
 * has crossed, by which point the level is gone. Colouring by side would also
 * spend the loudest channel on the one input here that is inferred rather than
 * published; the tooltip names the side instead.
 *
 * **Density comes from the published range, not from invented tiers.** The
 * crypto model spreads each candle's exposure over ten made-up leverage tiers,
 * which is most of why its field is dense. Here a session's exposure spreads
 * across the range that session actually traded in — both ends of which the
 * exchange publishes — shifted by the scan range. Same texture, nothing
 * invented. See `viop_margin_map.build_margin_map`.
 *
 * **One chart instance even with the profile on.** The two layers are read
 * against each other and two instances cannot be held in register through a
 * zoom; a volume bar four pixels off its price is worse than no volume bar.
 */
export default function ViopMarginMap({
  data,
  showProfile = false,
  height = 560,
}: ViopMarginMapProps) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);

  useEffect(() => {
    setPalette(readPalette());
  }, []);

  const ramp = useMemo(
    () =>
      buildRamp([
        palette['--heat-seq-1'],
        palette['--heat-seq-2'],
        palette['--heat-seq-3'],
        palette['--heat-seq-4'],
        // The tokens top out at a mid blue, which is where the theme needs them
        // — they also serve as backgrounds behind text. A heat ramp needs a
        // brighter place to land and no token is that colour, so the tip is the
        // one literal here.
        '#22d3ee',
      ]),
    [palette]
  );

  const option = useMemo(() => {
    const { grid, cells, sessions } = data;

    const prices = binPrices(grid.bins, grid.price_min, grid.bin_size);
    const days = sessions.map((session) => session.day);

    // `[column, binCentrePrice, total, long, short]`.
    const heatData = cells.map(([column, bin, longTry, shortTry]) => [
      column,
      prices[bin] ?? grid.price_min,
      longTry + shortTry,
      longTry,
      shortTry,
    ]);

    const ceiling = heatCeiling(cells.map(([, , longTry, shortTry]) => longTry + shortTry));

    const profileBins = data.volume_profile?.bins ?? [];
    const poc = pointOfControl(profileBins);
    const area = valueArea(profileBins);
    // ECharts wants [open, close, low, high].
    const candleData = sessions.map((session) => [
      session.open,
      session.close,
      session.low,
      session.high,
    ]);

    return {
      backgroundColor: 'transparent',
      animation: false,
      // Cross-hair rather than per-series pointers: on a field the reader is
      // asking "what price and which session is under my cursor", which is a
      // question about the axes, not about the mark they happen to be over.
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      // Edge to edge unless the profile is asked for. The field is the subject;
      // reserving a sixth of the width for a companion layer that is off by
      // default would crop the thing the reader came to look at.
      grid: showProfile
        ? [
            {
              left: 8,
              right: '17%',
              top: 8,
              bottom: 4,
              containLabel: true,
            },
            { left: '84%', right: 8, top: 8, bottom: 4, containLabel: true },
          ]
        : [
            {
              left: 8,
              right: 6,
              top: 8,
              bottom: 4,
              containLabel: true,
            },
          ],
      tooltip: {
        trigger: 'item',
        backgroundColor: palette['--surface'],
        borderColor: palette['--border'],
        borderWidth: 1,
        padding: [6, 9],
        textStyle: { color: palette['--fg'], fontSize: 11 },
        formatter: (raw: TooltipParams | TooltipParams[]) => {
          // ECharts passes an array when several items sit under the cursor and
          // omits `value` entirely for non-data targets. Neither shape is worth
          // a tooltip, but both reach this callback.
          const params = Array.isArray(raw) ? raw[0] : raw;
          if (!Array.isArray(params?.value)) return '';
          const value = params.value as number[];

          if (params.seriesType === 'candlestick') {
            // ECharts prepends the category index to a candlestick's value.
            const [index, open, close, low, high] = value;
            return [
              `<div style="color:${palette['--fg-muted']}">${days[index] ?? ''}</div>`,
              `A ${formatTry(open)}&nbsp;&nbsp;Y ${formatTry(high)}`,
              `D ${formatTry(low)}&nbsp;&nbsp;K ${formatTry(close)}`,
            ].join('<br/>');
          }

          if (params.seriesName === 'Spot hacim profili') {
            return [
              `<div style="color:${palette['--fg-muted']}">Spot hacim profili</div>`,
              `<b>${formatTry(value[1])}</b>`,
              `${formatCompact(value[0])} lot`,
            ].join('<br/>');
          }

          const [column, price, total, longTry, shortTry] = value;
          return [
            `<div style="color:${palette['--fg-muted']}">${days[column] ?? ''}</div>`,
            `<b>${formatTry(price)}</b>`,
            `Duran pozisyon <b>${formatCompactTry(total)}</b>`,
            `<span style="color:${palette['--up']}">Çık. uzun ${formatCompactTry(longTry)}</span>` +
              `&nbsp;&nbsp;<span style="color:${palette['--down']}">Çık. kısa ${formatCompactTry(
                shortTry
              )}</span>`,
          ].join('<br/>');
        },
      },
      xAxis: [
        {
          type: 'category',
          gridIndex: 0,
          data: days,
          boundaryGap: false,
          axisLine: { lineStyle: { color: palette['--border'] } },
          axisLabel: { color: palette['--fg-subtle'], fontSize: 10, hideOverlap: true },
          // Nothing drawn in the empty stretches. A grid there is chrome
          // competing with the field for the same pixels, and an empty bin is
          // meant to read as empty.
          splitLine: { show: false },
          axisPointer: {
            show: true,
            // Above every series. ECharts draws the pointer at z 0, which on a
            // density field puts the crosshair and its label *under* the cells
            // — unreadable the moment it crosses a bright row, which is exactly
            // where a reader puts it.
            z: 100,
            lineStyle: { color: palette['--border-strong'] },
            label: { backgroundColor: palette['--surface-2'], color: palette['--fg-muted'] },
          },
        },
        ...(!showProfile
          ? []
          : [
              {
                type: 'value',
                gridIndex: 1,
                min: 0,
                max: Math.max(...profileBins, 1),
                axisLine: { show: false },
                axisLabel: { show: false },
                axisTick: { show: false },
                splitLine: { show: false },
              },
            ]),
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          position: 'right',
          min: grid.price_min,
          max: grid.price_max,
          axisLine: { lineStyle: { color: palette['--border'] } },
          axisLabel: {
            color: palette['--fg-subtle'],
            fontSize: 10,
            formatter: (value: number) => value.toFixed(0),
          },
          splitLine: { show: false },
          // More ticks than an axis would normally take: on a price grid this
          // dense the reader is placing a level, not reading a round number.
          splitNumber: 12,
          axisPointer: {
            show: true,
            z: 100,
            lineStyle: { color: palette['--border-strong'] },
            label: {
              backgroundColor: palette['--surface-2'],
              color: palette['--fg-muted'],
              formatter: (params: { value: number }) => params.value.toFixed(2),
            },
          },
        },
        ...(!showProfile
          ? []
          : [
              {
                type: 'value',
                gridIndex: 1,
                min: grid.price_min,
                max: grid.price_max,
                axisLine: { show: false },
                axisLabel: { show: false },
                axisTick: { show: false },
                splitLine: { show: false },
              },
            ]),
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
        {
          type: 'inside',
          yAxisIndex: showProfile ? [0, 1] : 0,
          filterMode: 'none',
          zoomOnMouseWheel: false,
        },
      ],
      series: [
        {
          name: 'Teminat tarama yoğunluğu',
          type: 'custom',
          xAxisIndex: 0,
          yAxisIndex: 0,
          progressive: 4000,
          progressiveThreshold: 2000,
          data: heatData,
          z: 1,
          // Cells reach half a column either side of their own session, so the
          // first and last spill into the gutter unclipped — and only on the
          // rows that hold a cell there, which serrates the edge of the map.
          clip: true,
          renderItem: (_params: unknown, api: RenderApi) => {
            const centre = api.coord([api.value(0), api.value(1)]);
            const columnWidth = api.size([1, 0])[0];
            const rowHeight = api.size([0, grid.bin_size])[1];
            return {
              type: 'rect',
              shape: {
                x: centre[0] - columnWidth / 2,
                y: centre[1] - rowHeight / 2,
                // +0.6px closes the seams between neighbouring cells.
                width: columnWidth + 0.6,
                height: rowHeight + 0.6,
              },
              style: { fill: ramp[rampIndex(api.value(2), ceiling, ramp.length)] },
            };
          },
        },
        {
          name: 'Spot',
          type: 'candlestick',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: candleData,
          z: 5,
          itemStyle: {
            // Solid bodies rather than the hollow style used elsewhere in the
            // app: over a heat field an outline-only candle disappears into the
            // cells behind it.
            color: palette['--up'],
            color0: palette['--down'],
            borderColor: palette['--up'],
            borderColor0: palette['--down'],
            borderWidth: 1,
          },
        },
        ...(!showProfile
          ? []
          : [
              {
                // A custom series rather than a bar series, because the y axis has to
                // stay a *value* axis to line up with the field beside it, and an
                // ECharts bar across two value axes draws a hairline at the
                // coordinate instead of a bar reaching out from the edge.
                name: 'Spot hacim profili',
                type: 'custom',
                xAxisIndex: 1,
                yAxisIndex: 1,
                z: 2,
                clip: true,
                data: profileBins.map((value, index) => [value, prices[index], index]),
                renderItem: (_params: unknown, api: RenderApi) => {
                  const value = api.value(0);
                  if (value <= 0) return null;
                  const origin = api.coord([0, api.value(1)]);
                  const tip = api.coord([value, api.value(1)]);
                  const barHeight = Math.max(api.size([0, grid.bin_size])[1] - 1, 1);
                  const index = api.value(2);
                  const fill =
                    poc !== null && index === poc
                      ? palette['--heat-seq-4']
                      : area && index >= area.low && index <= area.high
                        ? palette['--fg-muted']
                        : palette['--border-strong'];
                  return {
                    type: 'rect',
                    shape: {
                      x: origin[0],
                      y: tip[1] - barHeight / 2,
                      width: Math.max(tip[0] - origin[0], 0),
                      height: barHeight,
                    },
                    style: { fill, opacity: 0.9 },
                  };
                },
              },
            ]),
      ],
    };
  }, [data, palette, ramp, showProfile]);

  return (
    <ReactECharts
      option={option}
      style={{ height, width: '100%' }}
      opts={{ renderer: 'canvas' }}
      notMerge
    />
  );
}
