'use client';

import { CommodityGroup, MacroCommodity } from '@/lib/api';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';
import SparklineChart from '@/components/overview/SparklineChart';
import Delta from './Delta';
import RangeBar from './RangeBar';
import { UNKNOWN, formatPrice } from './format';
import { metalBarClasses, metalClass } from './metals';

/** Groups in the order the panel lists them, heaviest macro signal first. */
const GROUP_ORDER: CommodityGroup[] = ['metals', 'energy', 'agriculture'];

const GROUP_LABEL: Record<CommodityGroup, string> = {
  metals: 'Metals',
  energy: 'Energy',
  agriculture: 'Agriculture',
};

/**
 * One commodity. The 24h move is the reading; the week is context underneath it.
 *
 * `unit` is always shown beside the price because the board mixes them: coffee at
 * 325.90 is US cents per pound and gold at 4,377.30 is dollars per ounce, and a
 * bare number invites the reader to compare the two.
 */
function CommodityRow({ row }: { row: MacroCommodity }) {
  const hasPrice = row.price !== null;
  const hasLine = row.sparkline.length > 1;
  const weekIsUp = (row.change_7d ?? 0) >= 0;

  return (
    <div className="px-4 py-2.5 border-b border-line last:border-b-0 hover:bg-surface-2 transition-colors">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className={`text-base truncate ${metalClass(row.symbol)}`}>{row.name}</div>
          <div className="text-2xs text-fg-subtle">{row.unit}</div>
        </div>

        <div className="shrink-0 w-[68px] h-8 flex items-center justify-end">
          {hasLine && <SparklineChart data={row.sparkline} positive={weekIsUp} />}
        </div>

        <div className="shrink-0 w-[104px] text-right">
          <div className={`text-base font-mono tabnum ${hasPrice ? 'text-fg' : 'text-fg-subtle'}`}>
            {hasPrice ? formatPrice(row.price as number) : UNKNOWN}
          </div>
          <Delta value={row.change_24h} className="text-2xs" />
        </div>
      </div>

      <div className="mt-2">
        <RangeBar
          price={row.price}
          low={row.low_52w}
          high={row.high_52w}
          accent={metalBarClasses(row.symbol)}
        />
      </div>
    </div>
  );
}

export default function CommodityPanel({
  rows,
  isLoading,
}: {
  rows: MacroCommodity[];
  isLoading: boolean;
}) {
  if (isLoading) return <PanelSkeleton />;

  // The footnote names both spans deliberately. The line is seven days and the
  // percentage is one, so a row can show a falling line beside a rising number —
  // true, but unreadable if you assume the two measure the same thing.
  return (
    <Panel
      title="Commodities"
      footnote="Front-month futures · line is 7 days, percentage is 24h · bar spans the 52-week range"
    >
      {GROUP_ORDER.map((group) => {
        const groupRows = rows.filter((row) => row.group === group);
        if (!groupRows.length) return null;

        return (
          <div key={group}>
            <div className="px-4 py-1.5 bg-surface-2 border-b border-line">
              <span className="label">{GROUP_LABEL[group]}</span>
            </div>
            {groupRows.map((row) => (
              <CommodityRow key={row.symbol} row={row} />
            ))}
          </div>
        );
      })}
    </Panel>
  );
}
