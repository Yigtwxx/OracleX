'use client';

import Link from 'next/link';

import { useBistCalendar } from '@/hooks/useBist';
import { EMPTY, formatDate, formatPercent, formatTry } from '@/lib/bist-format';

/**
 * What is coming, on the board rather than behind a tab.
 *
 * The same query the calendar page runs — `(90, 14)`, so React Query serves
 * both from one request — filtered forward. The page keeps the fortnight of
 * history because a reader arriving there is often checking a result that has
 * already been announced; a panel on the overview is answering "what is next",
 * and a dividend that went ex a week ago is not that.
 *
 * The date is printed once per day rather than on every row: three companies
 * reporting on the same morning is one fact about that morning, and repeating
 * the date three times makes it read as three.
 *
 * The horizon is stated in the footer. Without it a panel that opens on the
 * next fortnight reads as a calendar that only knows about the next fortnight,
 * and the reader has to scroll to the end to find out otherwise.
 */

const KIND_LABEL: Record<string, string> = {
  earnings: 'Bilanço',
  dividend: 'Temettü',
};

const KIND_TONE: Record<string, string> = {
  earnings: 'text-accent',
  dividend: 'text-up',
};

export default function OverviewCalendar() {
  const { data, isLoading } = useBistCalendar(90, 14);

  const today = new Date().toISOString().slice(0, 10);
  // The whole window, not a slice of it. The panel scrolls, and a cap here made
  // the board look like the calendar ended in three weeks when the query behind
  // it already reached three months out — the same horizon the tab shows.
  const upcoming = (data?.days ?? [])
    .filter((day) => day.day >= today)
    .flatMap((day) => day.events);

  const first = upcoming[0]?.day ?? null;
  const last = upcoming.length ? upcoming[upcoming.length - 1].day : null;

  let lastDay: string | null = null;

  return (
    <div className="surface surface-flat flex flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 className="text-base font-semibold text-fg">Takvim</h3>
        {/* No "see all" link: this panel is the whole calendar now. The tab it
            used to point at was the same ninety-day window with a day-grouped
            layout, and keeping a second copy of it behind a nav item was the
            reason it left. */}
        <span className="label">90 gün</span>
      </div>

      <ul className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
        {isLoading && upcoming.length === 0 && (
          <li className="px-3 py-4 text-sm text-fg-subtle">Yükleniyor…</li>
        )}
        {!isLoading && upcoming.length === 0 && (
          <li className="px-3 py-4 text-sm text-fg-subtle">
            Önümüzdeki dönemde tarihli bir olay yok.
          </li>
        )}

        {upcoming.map((event) => {
          const isNewDay = event.day !== lastDay;
          lastDay = event.day;
          return (
            <li key={`${event.kind}-${event.ticker}-${event.day}`}>
              {isNewDay && (
                <p className="label border-b border-line bg-surface-2 px-3 py-1">
                  {formatDate(event.day)}
                </p>
              )}
              <Link
                href={`/bist/hisseler/${event.ticker}`}
                className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5 text-sm transition-colors hover:bg-surface-2"
              >
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className={`label shrink-0 ${KIND_TONE[event.kind] ?? ''}`}>
                    {KIND_LABEL[event.kind] ?? event.kind}
                  </span>
                  <span className="truncate font-medium text-fg">{event.ticker}</span>
                </span>
                <span className="tabnum shrink-0 text-2xs text-fg-subtle">
                  {event.kind === 'dividend'
                    ? [
                        event.amount !== null ? formatTry(event.amount, 4) : null,
                        event.yield_pct !== null ? formatPercent(event.yield_pct) : null,
                      ]
                        .filter(Boolean)
                        .join(' · ') || EMPTY
                    : (event.sector ?? EMPTY)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>

      {/* How far this reaches, and what a calendar built from structured dates
          cannot cover — both said here rather than left to be discovered. */}
      {data && (
        <div className="shrink-0 border-t border-line px-3 py-1.5">
          {first && last && (
            <p className="label">
              {formatDate(first)} – {formatDate(last)} · {upcoming.length} olay
            </p>
          )}
          {data.excludes.length > 0 && (
            <p className="mt-0.5 text-2xs text-fg-subtle">
              Bedelli ve bedelsiz işlemler yapısal tarih taşımıyor; KAP akışında görünür.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
