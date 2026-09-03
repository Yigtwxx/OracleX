'use client';

import { useStore } from '@/store/useStore';
import AssetTag from '@/components/ui/AssetTag';
import { AdvancedRealTimeChart } from 'react-ts-tradingview-widgets';
import { BarChart3, Maximize2, Settings } from 'lucide-react';

export default function ChartPanel() {
  const { chartSymbol, selectedNews } = useStore();

  return (
    <div className="flex flex-col h-full">
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
          <button
            className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-2 transition-colors"
            title="Settings"
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
          <button
            className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-2 transition-colors"
            title="Fullscreen"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
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
