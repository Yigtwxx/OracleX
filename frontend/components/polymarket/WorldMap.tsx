'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { Minus, Plus, Maximize2 } from 'lucide-react';
import * as echarts from 'echarts';

import { formatMoney, formatProbability } from '@/lib/polymarket-format';
import type { PolymarketMap, PolymarketSubjectCountry } from '@/lib/api';

interface WorldMapProps {
  data: PolymarketMap;
  onSelectMarket: (slug: string) => void;
}

type LayerKey = 'jurisdictions' | 'subjects' | 'activity';

/** The subset of the chart instance the roam handler reads back. */
interface EChartsInstance {
  getOption: () => { geo?: { center?: unknown; zoom?: number }[] } | undefined;
  resize: () => void;
  getZr: () => { on: (event: string, handler: (p: { target?: unknown }) => void) => void };
}

/** The subset of an ECharts tooltip payload this map reads. */
interface TooltipParams {
  seriesType?: string;
  data?: unknown;
  value?: unknown;
}

/**
 * The subset of the custom-series render API this map uses.
 *
 * `value` is typed as returning `ParsedValue` upstream because a dimension can
 * hold a string; every dimension here is numeric, so it is narrowed at the call
 * site rather than being asserted away at the boundary.
 */
interface RenderApi {
  value: (index: number) => number | string | Date | null | undefined;
  coord: (point: number[]) => number[];
  getWidth: () => number;
  getHeight: () => number;
}

function asNumber(value: number | string | Date | null | undefined): number {
  return typeof value === 'number' ? value : Number(value) || 0;
}

/**
 * The three toggles, each carrying the colour its own layer draws in.
 *
 * The badge used to be coloured by provenance alone — green for measured, the
 * tab's magenta for derived, amber for estimated — which was a palette from
 * before the map was recoloured and matched nothing on the canvas underneath.
 * Tying it to the layer instead makes the chip point at what it controls: the
 * reader can see which switch owns the indigo countries and which owns the lime
 * dots without toggling them to find out.
 *
 * The words still say what the data is worth; only the colour changed hands.
 */
const LAYERS: { key: LayerKey; label: string; provenance: string; tint: string }[] = [
  {
    key: 'jurisdictions',
    label: 'Where it can be traded',
    provenance: 'Measured',
    // A lighter indigo than the countries themselves: the fill covers a whole
    // landmass and can afford to be dim, eleven pixels of text cannot.
    tint: '#818cf8',
  },
  {
    key: 'subjects',
    label: 'What the bets are about',
    provenance: 'Derived',
    tint: '#a3e635',
  },
  {
    key: 'activity',
    label: 'When the money moves',
    provenance: 'Estimated',
    // The bands are white at low alpha; at text size that has to become a solid
    // near-white or it disappears.
    tint: '#c7c7cf',
  },
];

/**
 * One vivid hue per tier, chosen for what survives a dark canvas.
 *
 * Three attempts got here, and the failures are the useful part. Mustard, red
 * and blue was mud: not because the hues were distinct, but because a dark
 * yellow *is* brown. Anything in the yellow-orange family loses its identity the
 * moment it is darkened enough to sit on this background, so it can never hold a
 * large area here. Retreating to greys fixed the mud and killed the layer — a
 * dark grey map on a dark canvas reads as switched off.
 *
 * Blues, indigos and cyans darken cleanly, keeping their hue all the way down.
 * So the tier covering thirty-three of the forty-two countries takes indigo,
 * where a large muted area still reads as a colour rather than as dirt. The two
 * small tiers can afford to be bright: rose for the five that are blocked
 * outright, cyan for the four that are only limited on the site.
 *
 * The vivid yellow that could not work here is spent on the bubbles instead,
 * where the shapes are small and painted at full strength — the one place in
 * this component that gold stays gold.
 */
const TIER_COLOR: Record<string, string> = {
  blocked: '#e11d48',
  close_only: '#4340b0',
  frontend_only: '#22d3ee',
};

/**
 * Unrestricted land.
 *
 * Spaced from the tiers by luminance rather than by even hex steps: at one
 * attempt the mildest tier sat close enough to this that Japan, Ireland and the
 * Netherlands read as unrestricted, which is the one thing the layer exists to
 * say they are not.
 */
const LAND_COLOR = '#1f1f26';
const LAND_BORDER = 'rgba(255,255,255,0.09)';

/**
 * The map's own country names, for the handful whose common name differs.
 *
 * The outline file uses Natural Earth's naming, so a jurisdiction list keyed by
 * ISO names does not line up with it out of the box. A country that fails to
 * match simply does not shade, which is a silent wrong answer — hence the table.
 */
const MAP_NAME: Record<string, string> = {
  'United States': 'United States of America',
  'Congo (Kinshasa)': 'Dem. Rep. Congo',
  'Central African Republic': 'Central African Rep.',
  'South Sudan': 'S. Sudan',
  'United States Minor Outlying Islands': '',
  'North Korea': 'North Korea',
};

/**
 * Longitude a UTC hour corresponds to, at 15° per hour.
 *
 * This is the inference the "estimated" badge is warning about, and it is worth
 * stating plainly: local solar noon at longitude L falls at UTC hour 12 − L/15,
 * so a burst of trading at 08:00 UTC lands over eastern Europe and the Gulf. It
 * says nothing about who was awake there, only when the money moved.
 */
function hourToLongitude(hour: number): number {
  const lon = (12 - hour) * 15;
  return lon > 180 ? lon - 360 : lon <= -180 ? lon + 360 : lon;
}

/**
 * The opening view, and the range the buttons may reach.
 *
 * Zoom 1 with the centre on the origin is not a guess — it is the only pair that
 * neither crops nor wastes. The box is 2:1 and, with `aspectScale: 1` below, so
 * is the world, so at zoom 1 the map fills it exactly.
 *
 * Both values were wrong before and each was wrong in its own direction. The
 * centre sat at 25°N, which puts the twenty-fifth parallel on the middle line of
 * the box and pushes everything below it downward: measured, the drawing sat
 * 208px low with a dead band across the top and Antarctica cut off the bottom.
 * The zoom sat at 1.15, which crops — and because the box and the world share an
 * aspect, it crops horizontally too, taking western Alaska and New Zealand off
 * the map to buy vertical room that was never needed.
 *
 * Past ~6x the 110m outlines stop having detail to show, so a deeper zoom only
 * magnifies the simplification.
 */
const MIN_ZOOM = 1;
const MAX_ZOOM = 6;
const ZOOM_STEP = 1.4;

/**
 * Centre of the opening view.
 *
 * Latitude 8 rather than 0 because the crop is not symmetric in what it costs.
 * Everything below -60 is ice and everything above 80 is empty ocean, but the
 * land between them is not centred on the equator — so the view is nudged north
 * far enough to keep northern Russia and Greenland while the crop takes the
 * Antarctic. At 25, where this sat before, the whole drawing was pushed 208px
 * down the box with a dead band across the top.
 */
const DEFAULT_CENTER: [number, number] = [0, 0];
const DEFAULT_ZOOM = 1;

//: The latitudes the outline data actually reaches, and the aspect that follows.
const LAT_NORTH = 83.6;
const LAT_SOUTH = -85.6;
const FULL_LAT_SPAN = LAT_NORTH - LAT_SOUTH;
const CONTENT_ASPECT = 360 / FULL_LAT_SPAN;

//: The southern edge worth keeping on screen. Cape Horn is at -56 and the
//: bottom of New Zealand at -47; below that there is only ice, so this is the
//: line the fit protects and everything past it is what gets cropped.
const KEEP_SOUTH = -56;

//: No air above Greenland: the northern edge sits flush against the top of the
//: frame. Every pixel spent above it is a pixel the crop has to take off the
//: bottom, and down there it comes out of Patagonia rather than out of ice.
const TOP_MARGIN = 0;

//: Callout geometry, in screen pixels rather than map units, so the label stays
//: the same size however far the map is zoomed.
const CALLOUT_WIDTH = 232;
const CALLOUT_PAD = 10;
const CALLOUT_LINE = 15;
const LEADER_RUN = 34;
const LEADER_RISE = 46;

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/**
 * The label that opens when a dot is clicked, and the elbow that ties it back.
 *
 * Drawn as a series in geo coordinates rather than as an HTML overlay pinned by
 * `convertToPixel`. The map pans without re-rendering React — that is what keeps
 * dragging smooth — so an overlay positioned from React state would sit still
 * while the map moved out from under it. A series is laid out by the chart on
 * every frame, so the label stays welded to its dot through both pan and zoom.
 *
 * The leader runs sideways and then up or down rather than straight to the box.
 * A diagonal over a map reads as a route between two places; a right-angled one
 * reads as a pointer, which is what it is.
 *
 * Which way it goes is decided per render from where the dot has ended up on
 * screen: away from the nearer edge, so the label does not open off-canvas when
 * the reader has panned its country to the margin.
 */
function buildCallout(row: PolymarketSubjectCountry): echarts.SeriesOption {
  const lines = [
    `${formatMoney(row.volume_usd)} · ${row.market_count} market${row.market_count === 1 ? '' : 's'}`,
    ...row.markets.slice(0, 3).map((m) => `• ${clip(m.question, 40)}`),
  ];
  const boxHeight = CALLOUT_PAD * 2 + CALLOUT_LINE * (lines.length + 1) + 4;

  return {
    type: 'custom',
    coordinateSystem: 'geo',
    z: 20,
    data: [[row.lon, row.lat]],
    renderItem: (_params: unknown, api: RenderApi) => {
      const [x, y] = api.coord([asNumber(api.value(0)), asNumber(api.value(1))]);
      const width = api.getWidth();
      const height = api.getHeight();

      // Which way to open is decided by measuring the room, not by which half
      // of the canvas the dot landed in. A ratio gets a dot near the edge wrong
      // — it opens outward and the label runs off the map — so each direction is
      // taken only if the whole box actually fits, and the clamp below catches
      // the case where neither does.
      const EDGE = 6;
      const needsX = LEADER_RUN + CALLOUT_WIDTH + EDGE;
      const goRight = x + needsX <= width || x - needsX < 0;
      const goDown = y + LEADER_RISE + boxHeight + EDGE <= height;

      const dx = goRight ? 1 : -1;
      const dy = goDown ? 1 : -1;

      const elbowX = x + dx * LEADER_RUN;
      const endY = y + dy * LEADER_RISE;

      const rawBoxX = goRight ? elbowX : elbowX - CALLOUT_WIDTH;
      const rawBoxY = goDown ? endY : endY - boxHeight;

      // Last resort for a dot with room on neither side: slide the box back
      // inside the canvas. The elbow still lands on it, so the pointer holds.
      const boxX = Math.min(Math.max(rawBoxX, EDGE), width - CALLOUT_WIDTH - EDGE);
      const boxY = Math.min(Math.max(rawBoxY, EDGE), height - boxHeight - EDGE);

      const textLeft = boxX + CALLOUT_PAD;
      let cursor = boxY + CALLOUT_PAD;

      const children: unknown[] = [
        {
          type: 'polyline',
          silent: true,
          shape: {
            points: [
              [x, y],
              [elbowX, y],
              [elbowX, endY],
            ],
          },
          style: {
            stroke: '#a3e635',
            lineWidth: 1,
            lineDash: [3, 3],
            fill: 'none',
            opacity: 0.85,
          },
        },
        {
          type: 'rect',
          shape: { x: boxX, y: boxY, width: CALLOUT_WIDTH, height: boxHeight, r: 6 },
          style: {
            fill: 'rgba(23,23,27,0.96)',
            stroke: 'rgba(163,230,53,0.5)',
            lineWidth: 1,
          },
        },
        {
          type: 'text',
          silent: true,
          style: {
            text: clip(row.country, 30),
            x: textLeft,
            y: cursor,
            fill: '#a3e635',
            font: '600 12px sans-serif',
            textVerticalAlign: 'top',
          },
        },
      ];

      cursor += CALLOUT_LINE + 4;
      for (const line of lines) {
        children.push({
          type: 'text',
          silent: true,
          style: {
            text: line,
            x: textLeft,
            y: cursor,
            fill: line.startsWith('•') ? '#9a9aa3' : '#e8e8ea',
            font: '11px sans-serif',
            textVerticalAlign: 'top',
          },
        });
        cursor += CALLOUT_LINE;
      }

      return { type: 'group', children };
    },
  } as echarts.SeriesOption;
}

export default function WorldMap({ data, onSelectMarket }: WorldMapProps) {
  const [registered, setRegistered] = useState(false);
  // Zoom is state because it changes only when a button is pressed. Pan is a
  // ref, and the difference matters: `georoam` fires on every mouse move of a
  // drag, and storing that in state re-rendered the chart under the cursor
  // mid-gesture — ECharts rebuilt, the drag lost its grip, and the map moved a
  // few pixels and stuck. A ref records where the reader panned to without
  // telling React, so the gesture runs uninterrupted and the position is still
  // there to restore the next time the option is rebuilt.
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  // The box in pixels. `layoutSize` needs a number rather than a percentage,
  // and the fit below is solved from both dimensions — see the geo block.
  const [box, setBox] = useState({ width: 0, height: 0 });
  const centerRef = useRef<[number, number]>(DEFAULT_CENTER);
  // Which dot has its callout open. One at a time: two labels on a world map
  // overlap each other more often than not, and the second one covers the
  // country the first is pointing at.
  const [selected, setSelected] = useState<string | null>(null);
  const chartRef = useRef<EChartsInstance | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState<Record<LayerKey, boolean>>({
    jurisdictions: true,
    subjects: true,
    activity: false,
  });

  useEffect(() => {
    let cancelled = false;
    // Served from our own origin rather than a CDN, and fetched once rather than
    // bundled: 170KB of country outlines in the JS payload would be paid for by
    // every page in the app, not just this one.
    fetch('/world.geo.json')
      .then((r) => r.json())
      .then((geo) => {
        if (cancelled) return;
        echarts.registerMap('world', geo);
        setRegistered(true);
      })
      .catch(() => setRegistered(false));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // ECharts measures its container once and then only listens for *window*
    // resizes. This box is sized by aspect-ratio against its own width, so it
    // changes height whenever the layout does — a scrollbar appearing, a
    // sibling collapsing, or the height cap itself being edited. When that
    // happens the canvas keeps its old size and paints outside the box, over
    // whatever follows it on the page. Observing the element closes the gap.
    // Depends on `registered`, and that is not incidental. Until the outlines
    // load this component returns a placeholder, so on first mount `boxRef` is
    // null — an effect with an empty dependency list ran once against nothing
    // and never attached the observer at all. The symptom was silent: the box
    // resized, the chart did not, and the derived zoom below never arrived.
    const node = boxRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      chartRef.current?.resize();
      const rect = node.getBoundingClientRect();
      setBox({ width: rect.width, height: rect.height });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    measure();
    return () => observer.disconnect();
  }, [registered]);

  const stepZoom = useCallback((factor: number) => {
    setZoom((current) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current * factor)));
  }, []);

  const resetView = useCallback(() => {
    centerRef.current = DEFAULT_CENTER;
    // Nudge it off and back when it already sits at the opening value, so the
    // option is rebuilt and the recentred view is actually applied.
    setZoom((current) => (current === DEFAULT_ZOOM ? DEFAULT_ZOOM + 0.0001 : DEFAULT_ZOOM));
  }, []);

  /**
   * How large to draw the map, solved from the latitudes worth keeping.
   *
   * Filling the width outright is the wrong target, and measuring showed why: at
   * 100% the world stands 752px tall in a 580px box, and the 172px that has to
   * go does not stop at Antarctica — it carries on through Cape Horn and the
   * bottom of New Zealand, leaving the visible edge at -45°.
   *
   * So the height is chosen first. The map is scaled so that everything from the
   * northern edge down to KEEP_SOUTH fits the box exactly, and the width follows
   * from the aspect. On a wide box that comes to about 93% of the width — a
   * margin thin enough not to read as one, bought with land nobody would accept
   * losing.
   *
   * `layoutCenter` then puts the map's top edge just inside the frame, so the
   * whole of the remaining overflow is Antarctic ice going off the bottom.
   */
  const fit = useMemo(() => {
    if (!box.width || !box.height) return null;
    const keepRatio = FULL_LAT_SPAN / (LAT_NORTH - KEEP_SOUTH);
    const width = Math.min(box.width, box.height * keepRatio * CONTENT_ASPECT);
    const height = width / CONTENT_ASPECT;
    return { width, centerY: height / 2 + TOP_MARGIN };
  }, [box]);

  const option = useMemo(() => {
    // Region styling on the geo component rather than a map series. Binding a
    // map series with `geoIndex` still left ECharts building its own coordinate
    // system whenever `map` was also set — which the type demands — so the
    // countries scaled separately from the bubbles drawn over them and vanished
    // entirely once zoomed. One geo, styled directly, has nothing to desync.
    const regions = active.jurisdictions
      ? data.jurisdictions.countries
          .map((c) => {
            const name = MAP_NAME[c.name] ?? c.name;
            if (!name) return null;
            const regionList = c.regions.length ? `Only: ${c.regions.join(', ')}` : '';
            return {
              name,
              itemStyle: { areaColor: TIER_COLOR[c.tier] },
              emphasis: { itemStyle: { areaColor: TIER_COLOR[c.tier] } },
              tooltip: {
                formatter: () =>
                  [
                    `<b>${name}</b>`,
                    data.jurisdictions.tier_labels[c.tier],
                    c.partial ? regionList : '',
                    c.note ? `<span style="opacity:.7">${c.note}</span>` : '',
                  ]
                    .filter(Boolean)
                    .join('<br/>'),
              },
            };
          })
          .filter((r): r is NonNullable<typeof r> => r !== null)
      : [];

    const maxVolume = Math.max(1, ...data.subjects.countries.map((c) => c.volume_usd));

    const series: echarts.SeriesOption[] = [];

    if (active.activity) {
      // Drawn under the bubbles: these are a backdrop, not a reading.
      series.push({
        type: 'custom',
        coordinateSystem: 'geo',
        silent: true,
        data: data.activity.hours.map((h) => [hourToLongitude(h.hour), 0, h.share, h.hour]),
        renderItem: (_params: unknown, api: RenderApi) => {
          const share = asNumber(api.value(2));
          const lon = asNumber(api.value(0));
          const topLeft = api.coord([lon - 7.5, 84]);
          const bottomRight = api.coord([lon + 7.5, -60]);
          return {
            type: 'rect',
            shape: {
              x: topLeft[0],
              y: topLeft[1],
              width: bottomRight[0] - topLeft[0],
              height: bottomRight[1] - topLeft[1],
            },
            style: {
              // Kept light. These bands sit over the jurisdiction colours, and
              // at the weight they started on they washed the map out — which
              // is backwards for the layer carrying the weakest claim on the
              // page. A backdrop should not outshout the measurement.
              // Neutral white rather than amber: between a red map and teal
              // bubbles, a third hue is the one that turns the canvas to mud.
              fill: `rgba(255, 255, 255, ${Math.min(0.14, share * 0.55)})`,
            },
          };
        },
      });
    }

    if (active.subjects) {
      series.push({
        type: 'scatter',
        coordinateSystem: 'geo',
        data: data.subjects.countries.map((c) => ({
          name: c.country,
          value: [c.lon, c.lat, c.volume_usd],
          markets: c.markets,
          marketCount: c.market_count,
        })),
        symbolSize: (value: number[]): number =>
          // Square root, so area rather than radius tracks volume — a radius
          // scale makes a market ten times bigger look a hundred times bigger.
          // Small on purpose now that clicking one opens a callout: a dot this
          // size marks a place, and the reading is in the label rather than in
          // how much of the map the dot covers.
          5 + 15 * Math.sqrt((value[2] ?? 0) / maxVolume),
        itemStyle: {
          // Lime, picked by measuring rather than by eye. The map below runs
          // indigo (242°), rose (347°) and cyan (188°); the widest gap left on
          // the wheel centres near 87°, and this sits in it — 96° from the
          // nearest colour the map already uses. Gold was the earlier pick and
          // cleared only 61°, which is why it kept reading as part of the map.
          color: 'rgba(163, 230, 53, 0.6)',
          borderColor: '#a3e635',
          borderWidth: 1,
        },
        emphasis: { itemStyle: { color: 'rgba(163, 230, 53, 0.95)' } },
        // No tooltip: clicking a dot draws the callout below, and a tooltip
        // saying the same thing on hover would fight it for the same space.
        tooltip: { show: false },
      });

      const chosen = selected
        ? data.subjects.countries.find((c) => c.country === selected)
        : undefined;

      if (chosen) {
        series.push(buildCallout(chosen));
      }
    }

    return {
      backgroundColor: 'transparent',
      // No animation anywhere on this chart. A zoom step re-lays out the geo and
      // the bubbles drawn over it, and animating them lets the two drift apart
      // for the length of the transition — the bubbles slide across the map and
      // catch up. A map has nothing to gain from an entrance animation either,
      // so the whole thing moves in one frame instead.
      animation: false,
      tooltip: {
        trigger: 'item',
        backgroundColor: '#17171b',
        borderColor: 'rgba(255,255,255,0.14)',
        textStyle: { color: '#e8e8ea', fontSize: 11 },
      },
      geo: {
        map: 'world',
        regions,
        // ECharts squashes longitude by 0.75 unless told otherwise, so a world
        // that is 2:1 in degrees renders at 1.5:1 and leaves a quarter of the
        // width empty however tall the box is. Measured before this line went
        // in: the map used 73.4% of the canvas. At 1 the projection is a plain
        // equirectangular, which is what the centroids and the hour bands are
        // already computed in — so the geometry agrees with itself as well.
        aspectScale: 1,
        // Fill the width, and pay for it in latitude.
        //
        // Left to itself ECharts fits the outlines inside the box and leaves a
        // margin — measured at 62% of the width on a 2.76:1 box, with the world
        // being 2.13:1. Trying to close that from outside by deriving a zoom was
        // the wrong lever: the numbers never reconciled because the padding is
        // ECharts' own. `layoutSize` sets the map's width directly instead.
        //
        layoutCenter: ['50%', fit ? fit.centerY : '50%'],
        // In pixels, not '100%'. A percentage here resolves against the
        // container's *height*, not its width — '100%' produced a 580px-wide
        // map in a 1600px box, measured at 36% of the width. Handing it the
        // measured width is unambiguous.
        layoutSize: fit ? fit.width : '100%',
        // 'move' rather than true: dragging pans, but the wheel and the
        // trackpad do not zoom. On a page that scrolls, a map that grabs the
        // wheel means a reader scrolling past it zooms it by accident and
        // loses their place instead. Zoom is on the buttons.
        roam: 'move',
        zoom,
        center: centerRef.current,
        // Not silent: this is what draws the countries now, so it has to take
        // the hover and the tooltip too.
        itemStyle: { areaColor: LAND_COLOR, borderColor: LAND_BORDER },
        emphasis: { label: { show: false }, itemStyle: { areaColor: '#26262d' } },
        select: { disabled: true },
      },
      series,
    } as echarts.EChartsOption;
  }, [data, active, zoom, selected, fit]);

  if (!registered) {
    return <div className="w-full aspect-[2/1] min-h-[360px] max-h-[580px] shimmer rounded-lg" />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 flex-wrap">
        {LAYERS.map((layer) => (
          <button
            key={layer.key}
            type="button"
            onClick={() => setActive((prev) => ({ ...prev, [layer.key]: !prev[layer.key] }))}
            aria-pressed={active[layer.key]}
            className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
              active[layer.key]
                ? 'border-line-strong text-fg bg-surface-2'
                : 'border-line text-fg-subtle hover:text-fg-muted'
            }`}
          >
            {layer.label}
            <span
              className="ml-1.5 text-2xs"
              style={{ color: layer.tint }}
              title={
                layer.provenance === 'Measured'
                  ? 'Read from a source that published it.'
                  : layer.provenance === 'Derived'
                    ? 'Computed from measurements by a rule you could re-run.'
                    : 'An inference. True of the input, uncertain of the conclusion.'
              }
            >
              {layer.provenance}
            </span>
          </button>
        ))}
      </div>

      {/* Always rendered, never conditional. Two reasons: it told the reader what
          the switch above is about to draw, so hiding it until after they had
          pressed the switch was backwards — and it made the map jump by a line
          on every toggle. Dimmed while the layer is off, so colours that are not
          currently on the canvas do not read as a live key. */}
      <div
        className={`flex items-center gap-3 flex-wrap text-2xs text-fg-subtle transition-opacity ${
          active.jurisdictions ? '' : 'opacity-40'
        }`}
      >
        <div className="contents">
          {(['blocked', 'close_only', 'frontend_only'] as const).map((tier) => (
            <span key={tier} className="inline-flex items-center gap-1.5">
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: TIER_COLOR[tier] }}
              />
              {data.jurisdictions.tier_labels[tier]}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 rounded-sm shrink-0"
              style={{ backgroundColor: LAND_COLOR, outline: `1px solid ${LAND_BORDER}` }}
            />
            Unrestricted
          </span>
        </div>
      </div>

      {/* Grab cursor on the wrapper: dragging is the only way to move this map
          now that the wheel is disabled, and an affordance nobody can see is an
          affordance nobody uses. ECharts leaves the canvas cursor alone and sets
          its own on the elements it makes interactive, so a bubble still reads
          as clickable. */}
      {/* Sized to the map's own 2:1 aspect rather than to a fixed height. At a
          flat 420px the box was about 3:1, so ECharts fitted the world by height
          and left a dead band down each side — the container was wide and the
          map was not. Matching the aspect spends the whole width on the map.
          The 580px cap is where it stops: at a typical window the aspect alone
          would make it 624px, which pushes the board fully below the fold. Past
          the cap the map goes back to being height-limited and gives up a little
          width — about 7% at 1248px, which is not visible — and that is the
          trade being made. `min-h` keeps it usable when the window is narrow. */}
      <div
        ref={boxRef}
        // `overflow-hidden` is the second half of the fix above: even if a
        // resize is missed, the canvas is clipped to its box rather than
        // spilling over the text underneath it.
        className="relative cursor-grab active:cursor-grabbing w-full aspect-[2/1] min-h-[360px] max-h-[580px] overflow-hidden rounded-lg"
      >
        <ReactECharts
          option={option}
          style={{ height: '100%', width: '100%' }}
          opts={{ renderer: 'canvas' }}
          notMerge
          onChartReady={(chart: {
            getZr: () => { on: (e: string, h: (p: { target?: unknown }) => void) => void };
          }) => {
            // A click that hits nothing dismisses the label. ECharts only
            // reports clicks that land on a series, so an empty patch of sea
            // has to be caught on the renderer itself.
            chart.getZr().on('click', (params) => {
              if (!params.target) setSelected(null);
            });
          }}
          onEvents={{
            click: (params: { seriesType?: string; componentType?: string; data?: unknown }) => {
              if (params.seriesType === 'scatter') {
                const row = params.data as { name?: string } | undefined;
                // Clicking the open dot again closes it, so the label is not a
                // trap the reader has to find a way out of.
                setSelected((current) => (current === row?.name ? null : (row?.name ?? null)));
                return;
              }
              // The callout itself opens the biggest market behind it — the
              // label lists the questions, so a click on it should reach one.
              if (params.seriesType === 'custom' && selected) {
                const row = data.subjects.countries.find((c) => c.country === selected);
                const first = row?.markets?.[0];
                if (first) onSelectMarket(first.slug);
              }
            },
            // Recorded, not rendered. Writing to a ref keeps the drag alive; a
            // setState here would rebuild the chart on every mouse move.
            georoam: (_params: unknown, chart: EChartsInstance) => {
              const geo = chart.getOption()?.geo?.[0];
              const next = geo?.center;
              if (Array.isArray(next) && next.length === 2) {
                centerRef.current = [Number(next[0]), Number(next[1])];
              }
            },
          }}
        />

        {/* Bottom right, over the canvas. Zoom lives here rather than on the
            wheel: this map sits inside a scrolling page, and a wheel-zooming
            map eats the scroll of anyone trying to get past it. */}
        <div className="absolute bottom-3 right-3 flex flex-col gap-1 cursor-default">
          <button
            type="button"
            onClick={() => stepZoom(ZOOM_STEP)}
            disabled={zoom >= MAX_ZOOM}
            aria-label="Zoom in"
            className="w-7 h-7 grid place-items-center rounded border border-line bg-surface/90 text-fg-muted hover:text-fg hover:bg-surface-2 disabled:opacity-40 disabled:hover:text-fg-muted transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => stepZoom(1 / ZOOM_STEP)}
            disabled={zoom <= MIN_ZOOM}
            aria-label="Zoom out"
            className="w-7 h-7 grid place-items-center rounded border border-line bg-surface/90 text-fg-muted hover:text-fg hover:bg-surface-2 disabled:opacity-40 disabled:hover:text-fg-muted transition-colors"
          >
            <Minus className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={resetView}
            aria-label="Reset the view"
            title="Reset the view"
            className="w-7 h-7 grid place-items-center rounded border border-line bg-surface/90 text-fg-muted hover:text-fg hover:bg-surface-2 transition-colors"
          >
            <Maximize2 className="w-3 h-3" />
          </button>
        </div>
      </div>

      <p className="text-2xs text-fg-subtle leading-relaxed">
        No layer here is &ldquo;where the money came from&rdquo;. Polymarket settles on Polygon and
        identifies a trader only by wallet, so no public data anywhere carries a bettor&rsquo;s
        location. {data.subjects.note} {data.activity.note} Access rules read from{' '}
        <a
          href={data.jurisdictions.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:underline"
        >
          Polymarket&rsquo;s own documentation
        </a>{' '}
        on {data.jurisdictions.retrieved}.
      </p>

      {active.activity && data.activity.hours.length > 0 && (
        <p className="text-2xs text-fg-subtle">
          Busiest UTC hour:{' '}
          {(() => {
            const top = [...data.activity.hours].sort((a, b) => b.share - a.share)[0];
            return `${String(top.hour).padStart(2, '0')}:00 (${formatProbability(top.share)} of sampled value)`;
          })()}{' '}
          · sampled from {data.activity.markets_sampled} markets
        </p>
      )}
    </div>
  );
}
