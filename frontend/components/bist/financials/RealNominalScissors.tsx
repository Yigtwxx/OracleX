'use client';

import type { BistFinancials } from '@/lib/bist-api';
import { FIELD_LABELS, indexedComparison } from '@/lib/bist-financials';

import AbsentPanel from './AbsentPanel';

/**
 * The board's argument, drawn once.
 *
 * One field indexed to 100 at the oldest deflated quarter and plotted twice:
 * the lira line and the purchasing-power line. Everything else on this page is
 * a chart of a company; this is a chart of the difference between two ways of
 * counting, and the gap widening left to right is the whole reading —
 * "üç katına çıktı, alım gücü olarak %8 büyüdü".
 *
 * DOM rather than ECharts. Each row is two bars and a text label with no axis
 * interaction, and the paired-bar shape is `positioning/RangeDistribution`'s,
 * which reflows and stays selectable where a canvas does not.
 */
export default function RealNominalScissors({
  payload,
  field,
}: {
  payload: BistFinancials;
  field: string;
}) {
  const { rows, basePeriod, rebased } = indexedComparison(payload, field);

  if (rows.length === 0) {
    return (
      <AbsentPanel>
        Reel karşılaştırma için çevrilebilmiş en az bir çeyrek gerekiyor; bu tahtada yok.
      </AbsentPanel>
    );
  }

  const ceiling = Math.max(100, ...rows.map((row) => Math.max(row.nominal ?? 0, row.real ?? 0)));

  return (
    <div className="space-y-2 px-1 py-1">
      <p className="text-2xs leading-relaxed text-fg-subtle">
        {FIELD_LABELS[field] ?? field}, {basePeriod} = 100.{' '}
        {rebased && 'Endeks serisi daha eski çeyrekleri kapsamadığı için baz bu çeyreğe kaydı. '}
        Üstteki çubuk kaç lira, alttaki o liranın ne aldığı.
      </p>

      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.period} className="grid grid-cols-[3.5rem_1fr] items-center gap-2">
            <span className="label shrink-0">{row.period}</span>
            <span className="space-y-1">
              <span className="flex items-center gap-2">
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                  <span
                    className="block h-full rounded-full bg-fg-muted"
                    style={{ width: `${((row.nominal ?? 0) / ceiling) * 100}%` }}
                  />
                </span>
                <span className="tabnum w-14 shrink-0 text-right text-2xs text-fg-muted">
                  {(row.nominal ?? 0).toFixed(0)}
                </span>
              </span>
              <span className="flex items-center gap-2">
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                  <span
                    className="block h-full rounded-full bg-accent"
                    style={{ width: `${((row.real ?? 0) / ceiling) * 100}%` }}
                  />
                </span>
                <span className="tabnum w-14 shrink-0 text-right text-2xs text-fg">
                  {(row.real ?? 0).toFixed(0)}
                </span>
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
