'use client';

import type { Ipo } from '@/lib/bist-api';
import { formatDate } from '@/lib/bist-format';
import { calendarLanes, ipoStateLabel, undatedRows } from '@/lib/bist-ipo';

const MONTH_LABEL = new Intl.DateTimeFormat('tr-TR', { month: 'long', year: 'numeric' });

function monthName(month: string): string {
  const [year, index] = month.split('-').map(Number);
  return MONTH_LABEL.format(new Date(year, index - 1, 1));
}

function Chip({ row }: { row: Ipo }) {
  return (
    <a
      href={row.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded border border-line px-2 py-1.5 transition-colors hover:border-line-strong hover:bg-surface-2"
    >
      <span className="flex items-baseline gap-1.5">
        <span className="text-2xs font-medium text-fg">
          {/* Dimmed rather than blank: the code does not exist yet, and an
              empty slot reads as a field we failed to fetch. */}
          {row.ticker ?? <span className="text-fg-subtle">kod atanmadı</span>}
        </span>
        <span className="min-w-0 flex-1 truncate text-2xs text-fg-muted">{row.company}</span>
      </span>
      <span className="mt-0.5 flex flex-wrap gap-x-2 text-2xs text-fg-subtle">
        {row.offer_dates && (
          <span>
            {formatDate(row.offer_dates.start)}
            {row.offer_dates.end !== row.offer_dates.start &&
              ` – ${formatDate(row.offer_dates.end)}`}
          </span>
        )}
        {row.price && (
          <span>
            {row.price.is_band ? `${row.price.low}–${row.price.high} TL` : `${row.price.low} TL`}
          </span>
        )}
        {row.market && <span>{row.market}</span>}
        <span>{ipoStateLabel(row.state)}</span>
      </span>
    </a>
  );
}

/**
 * What is coming, by the month the book opens.
 *
 * The tray at the end is the point of the component. An offering whose date the
 * calendar has not published cannot be placed on a month, and putting it on a
 * guessed one would be the single most misleading thing this board could do —
 * so it gets its own labelled group instead.
 */
export default function IpoCalendar({ rows }: { rows: Ipo[] }) {
  const lanes = calendarLanes(rows);
  const undated = undatedRows(rows);

  if (lanes.length === 0 && undated.length === 0) {
    return (
      <p className="px-1 py-6 text-center text-2xs text-fg-subtle">
        Bu pencerede ilan edilmiş halka arz yok.
      </p>
    );
  }

  return (
    <div className="custom-scrollbar max-h-[420px] space-y-3 overflow-y-auto pr-1">
      {lanes.map((lane) => (
        <section key={lane.month}>
          <h3 className="label mb-1.5">{monthName(lane.month)}</h3>
          <ul className="space-y-1.5">
            {lane.entries.map((row) => (
              <li key={row.slug}>
                <Chip row={row} />
              </li>
            ))}
          </ul>
        </section>
      ))}

      {undated.length > 0 && (
        <section>
          <h3 className="label mb-1.5">Tarihi belli değil</h3>
          <p className="mb-1.5 text-2xs text-fg-subtle">
            Takvim bu arzlar için henüz tarih yayımlamadı. Bir aya yerleştirilmediler.
          </p>
          <ul className="space-y-1.5">
            {undated.map((row) => (
              <li key={row.slug}>
                <Chip row={row} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
