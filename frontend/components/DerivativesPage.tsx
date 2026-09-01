'use client';

import { useState } from 'react';
import HeatmapWidget from './overview/HeatmapWidget';
import AdvancedHeatmap from './overview/AdvancedHeatmap';
import LiquidationHeatmap from './charts/LiquidationHeatmap';
import LiquidationLines from './charts/LiquidationLines';
import LiquidationMaps from './charts/LiquidationMaps';
import OpenInterestBoard from './charts/OpenInterestBoard';
import DexPerpBoard from './charts/DexPerpBoard';
import {
  BarChart3,
  Bitcoin,
  Boxes,
  LineChart,
  Layers,
  LayoutGrid,
  Rows3,
  TrendingUp,
} from 'lucide-react';

type DerivativesView =
  | 'advanced'
  | 'crypto'
  | 'nasdaq'
  | 'liquidation'
  | 'lines'
  | 'profile'
  | 'openinterest'
  | 'dexperps';

// Two groups, because the page holds two different kinds of thing. The first
// five are this terminal's own model of where leverage sits; the last three are
// general-purpose TradingView grids. They shared one undifferentiated row for
// as long as the page was named after the grids — now that it is named after
// the model, the row has to say which is which.
const VIEW_GROUPS: {
  label: string;
  views: { value: DerivativesView; label: string; icon: typeof Layers }[];
}[] = [
  {
    label: 'Positions',
    views: [
      { value: 'liquidation', label: 'Liquidation', icon: Layers },
      // Same model as 'liquidation', drawn as spans rather than as a grid: where
      // that view answers "where is the liquidity", this one answers "how long has
      // it been there, and at what leverage".
      { value: 'lines', label: 'Levels', icon: Rows3 },
      // The same book once more, with time taken out of it: the two above ask what
      // the liquidity has been doing, this one asks what a move from here costs.
      { value: 'profile', label: 'Map', icon: BarChart3 },
      // The input all three of the above are modelled from, on its own. It sits
      // after them because it is what you check once the book has told you
      // something — whether the exposure behind it is growing or unwinding.
      { value: 'openinterest', label: 'Open Interest', icon: TrendingUp },
      // Open interest again, cut by venue instead of by time. It follows the
      // aggregate because that is the order the question arrives in: first
      // whether exposure is growing, then whose book it is growing on.
      { value: 'dexperps', label: 'DEX Perps', icon: Boxes },
    ],
  },
  {
    label: 'Heatmaps',
    views: [
      { value: 'advanced', label: 'Advanced', icon: LayoutGrid },
      { value: 'crypto', label: 'Crypto', icon: Bitcoin },
      { value: 'nasdaq', label: 'Nasdaq', icon: LineChart },
    ],
  },
];

// Kept as a derived flat list so the existing default
// (`useState<DerivativesView>(VIEWS[0].value)`) keeps working unchanged — the order
// above is still the statement about priority, and a default that disagreed
// with it would be a silent third opinion.
const VIEWS = VIEW_GROUPS.flatMap((group) => group.views);

export default function DerivativesPage() {
  // The first tab, read off VIEWS rather than repeated — see the comment there.
  const [view, setView] = useState<DerivativesView>(VIEWS[0].value);

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="h-10 shrink-0 border-b border-line flex items-center px-4 gap-4 bg-surface">
        <h2 className="text-md font-semibold text-fg">Derivatives</h2>

        {/* Scrolls rather than wraps: the toolbar is a fixed h-10 band on every
            page of this terminal, and a row that grew to two lines here would
            shift the chart below it by ten pixels on exactly the widths where
            the chart has least room. Eight buttons plus two group labels no
            longer fit a narrow window, so the overflow goes sideways. */}
        <div className="flex items-center gap-2 min-w-0 overflow-x-auto">
          {VIEW_GROUPS.map((group, index) => (
            <div
              key={group.label}
              role="group"
              aria-label={group.label}
              className="flex items-center gap-2 shrink-0"
            >
              {index > 0 && <span className="h-4 w-px bg-line" aria-hidden />}
              <span className="text-2xs uppercase tracking-wide text-fg-subtle">{group.label}</span>
              <div className="flex gap-0.5">
                {group.views.map(({ value, label, icon: Icon }) => (
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
          ))}
        </div>
      </div>

      {/* Heatmap Content — every view but the TradingView embeds brings its own
          toolbar, so only those get the padded widget frame. */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {view === 'advanced' && <AdvancedHeatmap />}
        {view === 'liquidation' && <LiquidationHeatmap />}
        {view === 'lines' && <LiquidationLines />}
        {view === 'profile' && <LiquidationMaps />}
        {view === 'openinterest' && <OpenInterestBoard />}
        {view === 'dexperps' && <DexPerpBoard />}
        {(view === 'crypto' || view === 'nasdaq') && (
          <div className="p-3 h-full">
            <HeatmapWidget marketType={view} className="h-full w-full" />
          </div>
        )}
      </div>

      {/* Three views, one simulation — and the set is confusing enough without a
          legend. All of them are the same book of modelled liquidation prices;
          they disagree only on what is being asked of it. */}
      {(view === 'liquidation' || view === 'lines' || view === 'profile') && (
        <div className="shrink-0 border-t border-line bg-surface px-4 py-2 text-2xs text-fg-muted">
          <span className="text-fg-subtle">Liquidation</span> bins the book per candle and shades
          each cell by size — where liquidity is stacked right now.{' '}
          <span className="text-fg-subtle">Levels</span> keeps each cluster whole and draws it as a
          span, from the candle that created it to the candle that swept it — how long a level
          survived, and at what leverage. <span className="text-fg-subtle">Map</span> drops time
          altogether and stacks what is standing now against price, so a bar is what a move to that
          price would liquidate. One simulation behind all three, run against whichever
          exchange&apos;s own statistics you pick — and none of them is observed liquidation data.
          Only Map can sum the venues: the other two are indexed by candle, and three exchanges do
          not share one.
        </div>
      )}
    </div>
  );
}
