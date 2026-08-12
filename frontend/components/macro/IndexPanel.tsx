'use client';

import { MacroIndex } from '@/lib/api';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';
import SparklineChart from '@/components/overview/SparklineChart';
import Delta from './Delta';
import { UNKNOWN, formatPrice } from './format';
import { BLOC_LABEL, BLOC_ORDER, regionMeta } from './regions';

/**
 * Session badge for a bloc.
 *
 * Three states, and "unknown" is one of them: a badge that says "Closed" during
 * trading hours is worse than one that admits it could not tell. The class pairs
 * are literal strings — Tailwind scans source text, and a class assembled from a
 * variable is never generated.
 */
const SESSION_STYLE: Record<string, string> = {
  open: 'text-up border-up',
  closed: 'text-fg-subtle border-line',
  unknown: 'text-fg-subtle border-line',
};

function SessionBadge({ status, label }: { status: string; label: string }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded border text-2xs uppercase tracking-wide ${
        SESSION_STYLE[status] ?? SESSION_STYLE.unknown
      }`}
      title="Ordinary cash session; public holidays are not accounted for"
    >
      {label}
    </span>
  );
}

function IndexRow({ row }: { row: MacroIndex }) {
  const hasPrice = row.price !== null;
  const hasLine = row.sparkline.length > 1;
  const weekIsUp = (row.change_7d ?? 0) >= 0;

  return (
    <div className="px-4 py-2.5 border-b border-line last:border-b-0 hover:bg-surface-2 transition-colors flex items-center gap-3">
      <span className="shrink-0 text-base leading-none" aria-hidden="true">
        {regionMeta(row.region).flag}
      </span>

      <div className="min-w-0 flex-1">
        <div className="text-base text-fg truncate">{row.name}</div>
        <div className="text-2xs text-fg-subtle">{row.symbol}</div>
      </div>

      <div className="shrink-0 w-[68px] h-8 flex items-center justify-end">
        {hasLine && <SparklineChart data={row.sparkline} positive={weekIsUp} />}
      </div>

      <div className="shrink-0 w-[112px] text-right">
        <div className={`text-base font-mono tabnum ${hasPrice ? 'text-fg' : 'text-fg-subtle'}`}>
          {hasPrice ? formatPrice(row.price as number) : UNKNOWN}
        </div>
        <Delta value={row.change_24h} className="text-2xs" />
      </div>
    </div>
  );
}

export default function IndexPanel({
  rows,
  isLoading,
}: {
  rows: MacroIndex[];
  isLoading: boolean;
}) {
  if (isLoading) return <PanelSkeleton />;

  return (
    <Panel
      title="Global Indices"
      footnote="Line is 7 days, percentage is 24h · badge is the ordinary session, not today's calendar"
    >
      {BLOC_ORDER.map((bloc) => {
        const blocRows = rows.filter((row) => regionMeta(row.region).bloc === bloc);
        if (!blocRows.length) return null;

        // Every exchange in a bloc keeps its own hours, so the header badge shows
        // the bloc's own state only when its members agree. A mixed bloc gets no
        // badge rather than one row's session presented as all of them.
        const statuses = new Set(blocRows.map((row) => row.market_status.status));
        const shared = statuses.size === 1 ? blocRows[0].market_status : null;

        return (
          <div key={bloc}>
            <div className="px-4 py-1.5 bg-surface-2 border-b border-line flex items-center justify-between gap-2">
              <span className="label">{BLOC_LABEL[bloc]}</span>
              {shared && <SessionBadge status={shared.status} label={shared.label} />}
            </div>
            {blocRows.map((row) => (
              <IndexRow key={row.symbol} row={row} />
            ))}
          </div>
        );
      })}
    </Panel>
  );
}
