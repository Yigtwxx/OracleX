'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '@/store/useStore';
import AssetTag from '@/components/ui/AssetTag';
import { AdvancedRealTimeChart } from 'react-ts-tradingview-widgets';
import { BarChart3, Maximize2, Minimize2 } from 'lucide-react';

/**
 * Vendor-prefixed fullscreen, which is still the only way in on Safari.
 *
 * The standard names have been unprefixed everywhere else for years, but
 * WebKit only ever shipped `webkitRequestFullscreen` — so a feature detection
 * on `requestFullscreen` alone reports "not supported" on the one browser this
 * panel is most cramped in, and the button would have gone back to doing
 * nothing for that reader.
 */
type FullscreenElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void;
};
type FullscreenDocument = Document & {
  webkitFullscreenElement?: Element | null;
  webkitExitFullscreen?: () => Promise<void> | void;
  webkitFullscreenEnabled?: boolean;
};

function currentFullscreenElement(): Element | null {
  if (typeof document === 'undefined') return null;
  const doc = document as FullscreenDocument;
  return doc.fullscreenElement ?? doc.webkitFullscreenElement ?? null;
}

export default function ChartPanel() {
  const { chartSymbol, selectedNews } = useStore();
  const panelRef = useRef<HTMLDivElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Read from the event rather than from our own click, because this state has
  // more than one author: Escape and the browser's own chrome exit fullscreen
  // without going through the button, and a flag we set ourselves would then
  // show "Exit fullscreen" over a panel that is no longer in it.
  useEffect(() => {
    const sync = () => setIsFullscreen(currentFullscreenElement() === panelRef.current);
    document.addEventListener('fullscreenchange', sync);
    document.addEventListener('webkitfullscreenchange', sync);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      document.removeEventListener('webkitfullscreenchange', sync);
    };
  }, []);

  const toggleFullscreen = useCallback(async () => {
    const panel = panelRef.current as FullscreenElement | null;
    if (!panel) return;
    const doc = document as FullscreenDocument;

    try {
      if (currentFullscreenElement() === panel) {
        await (doc.exitFullscreen?.() ?? doc.webkitExitFullscreen?.());
      } else {
        await (panel.requestFullscreen?.() ?? panel.webkitRequestFullscreen?.());
      }
    } catch {
      // The request rejects when the gesture is not trusted or an iframe
      // policy forbids it. Nothing to recover — `fullscreenchange` never
      // fires, so the button keeps its current label, which is accurate.
    }
  }, []);

  // Resolved after mount, never during render. The server has no `document`,
  // so deciding this inline would render the button on the client and not in
  // the SSR output — a hydration mismatch, and React would discard the whole
  // subtree to recover. Starting false and turning it on costs one paint of a
  // header with no button, which is also the honest state before we know.
  const [supported, setSupported] = useState(false);
  useEffect(() => {
    const doc = document as FullscreenDocument;
    setSupported(Boolean(doc.fullscreenEnabled || doc.webkitFullscreenEnabled));
  }, []);

  return (
    // `bg-bg` on the panel itself, not only on the chart area: a fullscreened
    // element is painted against the browser's backdrop rather than the page,
    // so a transparent header would sit on black in a light theme.
    <div ref={panelRef} className="flex flex-col h-full bg-bg">
      {/* Header - Fixed height to align with other panels */}
      <div className="h-10 shrink-0 px-4 border-b border-line flex items-center justify-between bg-surface">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-3.5 h-3.5 text-fg-muted" />
          <h2 className="text-base font-semibold text-fg">Chart</h2>
          <span className="text-xs font-mono text-fg-subtle">
            {chartSymbol.split(':')[1] || chartSymbol}
          </span>
        </div>
        <div className="flex items-center gap-0.5">
          {/* No settings button beside this one. The widget below renders its
              own toolbar — interval, chart style, indicators — so a second
              control would either duplicate it or need a meaning invented for
              it, which is what left the old one wired to nothing. */}
          {supported && (
            <button
              type="button"
              onClick={toggleFullscreen}
              aria-label={isFullscreen ? 'Exit fullscreen' : 'Show the chart fullscreen'}
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-2 transition-colors"
            >
              {isFullscreen ? (
                <Minimize2 className="w-3.5 h-3.5" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5" />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Active Symbol Banner */}
      {selectedNews && (
        <div className="shrink-0 px-4 py-1.5 border-b border-line bg-surface-2 flex items-center gap-2 min-w-0">
          <span className="shrink-0">
            <AssetTag symbol={selectedNews.symbol} size="md" />
          </span>
          {/* An unattributed item leaves the chart on whatever was already
              shown, so say so rather than letting the banner imply the chart
              below belongs to this story. */}
          {!selectedNews.symbol && (
            <span className="text-xs text-fg-subtle shrink-0">no asset</span>
          )}
          <span className="text-xs text-fg-subtle truncate">{selectedNews.title}</span>
        </div>
      )}

      {/* Chart Area */}
      <div className="flex-1 min-h-0 relative bg-bg">
        <AdvancedRealTimeChart
          key={chartSymbol}
          symbol={chartSymbol}
          theme="dark"
          autosize
          interval="D"
          timezone="Etc/UTC"
          style="1"
          locale="en"
          enable_publishing={false}
          hide_top_toolbar={false}
          hide_legend={false}
          save_image={false}
          container_id={`tradingview_${chartSymbol.replace(':', '_')}`}
          copyrightStyles={{
            parent: {
              display: 'none',
            },
          }}
        />
      </div>
    </div>
  );
}
