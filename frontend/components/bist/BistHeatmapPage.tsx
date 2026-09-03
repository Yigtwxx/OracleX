'use client';

import { useMemo, useState } from 'react';
import { AlertTriangle, Gauge, LayoutGrid, RefreshCw, Rows3 } from 'lucide-react';

import { useBistHeatmap } from '@/hooks/useBist';
import type { BistHeatmapTile } from '@/lib/bist-api';
import { BIST_METRIC_CONFIG, metricIsEmpty, type BistHeatMetric } from '@/lib/bist-heatmap';
import BistPageShell from '@/components/bist/BistPageShell';
import HeatmapBoard from '@/components/bist/heatmap/HeatmapBoard';
import HeatmapDetail from '@/components/bist/heatmap/HeatmapDetail';
import HeatmapLegend from '@/components/bist/heatmap/HeatmapLegend';
import HeatmapSectorBoard from '@/components/bist/heatmap/HeatmapSectorBoard';
import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup, { type ToggleOption } from '@/components/ui/ToggleGroup';

/**
 * The four the page offers, not the seven the API accepts.
 *
 * XBANK, XKTUM and XK100 are real and answer fine, but they are subsets a
 * reader reaches for by name rather than boards they browse; four segments is
 * already the width this toolbar has.
 */
const INDEX_OPTIONS: ToggleOption<string>[] = [
  { value: 'XU100', label: 'BIST 100' },
  { value: 'XU030', label: 'BIST 30' },
  { value: 'XU050', label: 'BIST 50' },
  // "BIST Tüm", not "all listings": XUTUM is an index with its own membership
  // (578 names against 625 listings on the board), and labelling it "Tümü"
  // would promise a board of everything that trades.
  { value: 'XUTUM', label: 'BIST Tüm' },
];

const METRIC_OPTIONS: ToggleOption<BistHeatMetric>[] = (
  ['change', 'traded_value', 'open_interest'] as const
).map((metric) => ({
  value: metric,
  label: BIST_METRIC_CONFIG[metric].label,
  icon: BIST_METRIC_CONFIG[metric].icon,
}));

type ViewMode = 'flat' | 'sector';

const VIEW_OPTIONS: ToggleOption<ViewMode>[] = [
  { value: 'flat', label: 'Düz', icon: LayoutGrid },
  { value: 'sector', label: 'Sektöre göre', icon: Rows3 },
];

/**
 * Where the money in an index sits, and which way it moved.
 *
 * Area is market capitalisation on every metric. Colour is what changes when
 * the reader changes the question — binding size to the metric too would make
 * the same company a different size depending on what was being asked, and the
 * one thing a treemap is good at is holding proportion still.
 */
export default function BistHeatmapPage() {
  const [index, setIndex] = useState('XU100');
  const [metric, setMetric] = useState<BistHeatMetric>('change');
  const [view, setView] = useState<ViewMode>('flat');
  const [selected, setSelected] = useState<BistHeatmapTile | undefined>(undefined);

  const { data, isLoading, isError, error, refetch } = useBistHeatmap(index);

  const tiles = useMemo(() => data?.tiles ?? [], [data]);
  const emptyMetric = tiles.length > 0 && metricIsEmpty(tiles, metric);
  const futuresMissing = data !== undefined && !data.has_futures_data;

  const board = (() => {
    if (isLoading && !data) {
      return <StatusMessage icon={RefreshCw}>Isı haritası yükleniyor…</StatusMessage>;
    }
    // A cold failure only. With a board already on screen the staleness strip
    // says the refresh failed and the last good data stays up.
    if (isError && !data) {
      return (
        <StatusMessage
          icon={AlertTriangle}
          action={
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-1 rounded-md border border-line px-2.5 py-1 text-sm text-fg-muted hover:text-fg"
            >
              Tekrar dene
            </button>
          }
        >
          {error instanceof Error
            ? `Borsa İstanbul verisi şu an alınamıyor. (${error.message})`
            : 'Borsa İstanbul verisi şu an alınamıyor.'}
        </StatusMessage>
      );
    }
    if (tiles.length === 0) {
      return <StatusMessage icon={Gauge}>Bu endekste gösterilecek hisse yok.</StatusMessage>;
    }
    if (emptyMetric) {
      return <StatusMessage icon={Gauge}>{BIST_METRIC_CONFIG[metric].emptyHint}</StatusMessage>;
    }
    if (view === 'sector') {
      return (
        <HeatmapSectorBoard
          tiles={tiles}
          sectors={data?.sectors ?? []}
          metric={metric}
          selectedTicker={selected?.ticker}
          onSelect={setSelected}
        />
      );
    }
    return (
      <HeatmapBoard
        tiles={tiles}
        metric={metric}
        selectedTicker={selected?.ticker}
        onSelect={setSelected}
        height={620}
      />
    );
  })();

  return (
    <BistPageShell
      title="Isı Haritası"
      description="Alan piyasa değerini, renk seçtiğiniz metriği taşır. VİOP kontratı olan hisselerde açık pozisyon rozeti."
      delayed
      action={
        data && (
          <span className="tabnum text-2xs text-fg-subtle">
            {data.shown} / {data.total} hisse
          </span>
        )
      }
    >
      <div className="surface surface-flat overflow-hidden">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
          <ToggleGroup label="Endeks" options={INDEX_OPTIONS} value={index} onChange={setIndex} />
          <ToggleGroup
            label="Renk metriği"
            options={METRIC_OPTIONS}
            value={metric}
            onChange={setMetric}
          />
          <ToggleGroup label="Görünüm" options={VIEW_OPTIONS} value={view} onChange={setView} />
          {/* States the encoding out loud. Without it, area is an unexplained
              visual channel — and a reader who assumes it tracks the metric
              reads every board backwards. */}
          {/* The label goes in verbatim. Lower-casing it read better on the
              first two metrics and turned VİOP into "viop" on the third —
              an acronym is not a word, and Turkish casing rules make the
              round trip lossy besides. */}
          <span className="ml-auto text-2xs text-fg-subtle">
            Alan: piyasa değeri · Renk: {BIST_METRIC_CONFIG[metric].label}
          </span>
        </div>

        {data && (data.stale || data.viop_stale || isError) && (
          <div className="border-b border-line px-3 py-1">
            <StaleStrip
              stale={data.stale}
              refreshFailed={isError}
              asOf={data.as_of}
              onRetry={() => refetch()}
            />
          </div>
        )}

        {/* A missing futures column is said rather than shown. A board of grey
            badges leaves the reader to guess whether nobody is positioned or
            nobody could be asked. */}
        {futuresMissing && !emptyMetric && (
          <div className="border-b border-line px-3 py-1 text-2xs text-fg-muted">
            VİOP tablosu şu an okunamıyor — açık pozisyon sütunu boş.
          </div>
        )}

        <div className="p-2">{board}</div>
      </div>

      {/* Outside the board's card, and that placement is the whole point.
          `sticky` resolves against the nearest scrolling ancestor, and the card
          is `overflow-hidden` — inside it the panel sticks to a box that never
          scrolls, which looks exactly like sticky not working. Out here the
          ancestor is the page scroller.

          It needs to stick at all because the sector view runs to nineteen
          sections: a detail panel that far below the tile you just clicked is a
          panel you never see update, and the legend has the same problem. */}
      <div className="surface surface-flat sticky bottom-0 z-10 overflow-hidden">
        <HeatmapDetail tile={selected} />
        <div className="border-t border-line p-2">
          <HeatmapLegend metric={metric} />
        </div>
      </div>
    </BistPageShell>
  );
}
