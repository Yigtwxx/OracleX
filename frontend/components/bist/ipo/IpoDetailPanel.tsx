'use client';

import FundAllocationBar from '@/components/bist/FundAllocationBar';
import type { Ipo } from '@/lib/bist-api';
import { EMPTY, formatCompact, formatPercent } from '@/lib/bist-format';
import {
  absentCopy,
  allocationSegments,
  proceedsSegments,
  structureSegments,
} from '@/lib/bist-ipo';

function Block({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-1">
      <h4 className="label">{title}</h4>
      {children}
      {note && <p className="text-2xs text-fg-subtle">{note}</p>}
    </section>
  );
}

function Absent({ children }: { children: string }) {
  return (
    <p className="border-t border-dashed border-line pt-1.5 text-2xs text-fg-subtle">{children}</p>
  );
}

/**
 * One offering's three published breakdowns, under the row it belongs to.
 *
 * `FundAllocationBar` is reused rather than reimplemented: its documented
 * behaviours are exactly right here — a segment never rounds itself out of
 * existence, and a total under 100% leaves bare track instead of stretching,
 * which is the honest rendering of a filing whose parts do not quite add up.
 */
export default function IpoDetailPanel({ row }: { row: Ipo }) {
  const allocation = allocationSegments(row.results);
  const structure = structureSegments(row.structure);
  const proceeds = proceedsSegments(row.use_of_proceeds);

  return (
    <div className="grid gap-4 border-t border-line bg-surface-2/40 px-3 py-3 lg:grid-cols-3">
      <Block
        title="Yatırımcı dağılımı"
        note={
          row.results?.total_investors != null
            ? `${formatCompact(row.results.total_investors, 0)} yatırımcı katıldı.`
            : undefined
        }
      >
        {allocation ? (
          <FundAllocationBar segments={allocation.segments} total={allocation.total} showLegend />
        ) : (
          <Absent>{absentCopy(row, 'results')}</Absent>
        )}
      </Block>

      <Block
        title="Arz şekli"
        note={
          structure
            ? `Sermaye artırımı şirkete para girer; ortak satışı satan ortağa. ${
                row.structure?.spk_bulletin ? `SPK Bülteni ${row.structure.spk_bulletin}.` : ''
              }`
            : undefined
        }
      >
        {structure ? (
          <FundAllocationBar segments={structure.segments} total={structure.total} showLegend />
        ) : (
          <Absent>{absentCopy(row, 'structure')}</Absent>
        )}
      </Block>

      <Block title="Fonun kullanım yeri" note={row.proceeds_source ?? undefined}>
        {proceeds ? (
          <FundAllocationBar segments={proceeds.segments} total={proceeds.total} showLegend />
        ) : (
          <Absent>{absentCopy(row, 'proceeds')}</Absent>
        )}
      </Block>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-2xs lg:col-span-3 lg:grid-cols-4">
        {[
          ['Aracı kurum', row.broker],
          ['Dağıtım yöntemi', row.method],
          ['Pazar', row.market],
          ['Arz büyüklüğü', row.lots != null ? `${formatCompact(row.lots, 1)} lot` : null],
          ['Fiili dolaşım', formatPercent(row.free_float_pct, 2)],
          ['İlk işlem', row.listing_date],
        ].map(([label, value]) => (
          <div key={label as string} className="flex flex-col">
            <dt className="label">{label}</dt>
            <dd className="text-fg-muted">{value || EMPTY}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
