'use client';

import { CryptoCoinsHeatmap, StockHeatmap } from 'react-ts-tradingview-widgets';
import { Layers } from 'lucide-react';

interface HeatmapWidgetProps {
  marketType?: 'crypto' | 'nasdaq';
  className?: string;
}

export default function HeatmapWidget({
  marketType = 'crypto',
  className = '',
}: HeatmapWidgetProps) {
  const title = marketType === 'nasdaq' ? 'Nasdaq Heatmap' : 'Crypto Heatmap';

  return (
    <div className={`surface flex flex-col h-full p-3 overflow-hidden ${className}`}>
      <div className="flex items-center gap-2 mb-2.5 shrink-0">
        <Layers className="w-3.5 h-3.5 text-fg-muted" />
        <h3 className="text-base font-semibold text-fg">{title}</h3>
      </div>

      <div className="relative flex-1 min-h-[150px] w-full rounded-md overflow-hidden border border-line bg-bg">
        {marketType === 'crypto' && (
          <CryptoCoinsHeatmap colorTheme="dark" width="100%" height="100%" locale="en" />
        )}
        {marketType === 'nasdaq' && (
          <StockHeatmap
            colorTheme="dark"
            width="100%"
            height="100%"
            exchanges={['NASDAQ']}
            locale="en"
            dataSource="SPX500"
          />
        )}
      </div>
    </div>
  );
}
