'use client';

import { useState } from 'react';
import HeatmapWidget from './overview/HeatmapWidget';
import AdvancedHeatmap from './overview/AdvancedHeatmap';
import LiquidationHeatmap from './charts/LiquidationHeatmap';
import { Bitcoin, LineChart, Layers, LayoutGrid } from 'lucide-react';

type HeatmapView = 'advanced' | 'crypto' | 'nasdaq' | 'liquidation';

const VIEWS: { value: HeatmapView; label: string; icon: typeof Layers }[] = [
  { value: 'advanced', label: 'Advanced', icon: LayoutGrid },
  { value: 'crypto', label: 'Crypto', icon: Bitcoin },
  { value: 'nasdaq', label: 'Nasdaq', icon: LineChart },
  { value: 'liquidation', label: 'Liquidation', icon: Layers },
];

export default function HeatmapPage() {
  const [view, setView] = useState<HeatmapView>('advanced');

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="h-10 shrink-0 border-b border-line flex items-center px-4 gap-4 bg-surface">
        <h2 className="text-md font-semibold text-fg">Market Heatmap</h2>

        <div className="flex gap-0.5">
          {VIEWS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              onClick={() => setView(value)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-sm transition-colors ${
                view === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
              }`}
            >
              <Icon className="w-3 h-3" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Heatmap Content — the advanced and liquidation views bring their own
          toolbars, so only the TradingView embeds get the widget frame. */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {view === 'advanced' && <AdvancedHeatmap />}
        {view === 'liquidation' && <LiquidationHeatmap />}
        {(view === 'crypto' || view === 'nasdaq') && (
          <div className="p-3 h-full">
            <HeatmapWidget marketType={view} className="h-full w-full" />
          </div>
        )}
      </div>
    </div>
  );
}
