import { MacroEvent } from '@/lib/api';
import { AlertCircle } from 'lucide-react';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';

interface MacroCalendarProps {
  data: MacroEvent[];
  isLoading: boolean;
  isError: boolean;
}

/** Input format is "MM-DD-YYYY". Returns null when the string is unusable. */
function parseDate(dateStr: string): Date | null {
  if (!dateStr) return null;
  const [m, d, y] = dateStr.split('-');
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDay(dateStr: string): string {
  const date = parseDate(dateStr);
  if (!date) return dateStr;
  return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

interface DayGroup {
  date: string;
  events: MacroEvent[];
}

/**
 * Collapse the flat feed into one block per day.
 *
 * The list now runs a month rather than the rest of a week, which is far more
 * rows than fit the panel at once. Repeating the date on every row was legible
 * over five entries and is noise over a hundred; hoisting it into a heading
 * turns the scroll into something a reader can skim by date.
 */
function groupByDay(events: MacroEvent[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const event of events) {
    const last = groups[groups.length - 1];
    if (last && last.date === event.date) {
      last.events.push(event);
    } else {
      groups.push({ date: event.date, events: [event] });
    }
  }
  return groups;
}

/**
 * How far ahead the list actually reaches, read off the rows.
 *
 * The endpoint answers with a bare list from whichever source responded, and the
 * fallback covers a week where the primary covers a month. Deriving the horizon
 * here means a short list says so instead of quietly implying a quiet month.
 */
function horizonNote(events: MacroEvent[]): string {
  const last = parseDate(events[events.length - 1]?.date ?? '');
  if (!last) return 'Upcoming releases only';
  const through = last.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `Upcoming releases through ${through}`;
}

export default function MacroCalendar({ data, isLoading, isError }: MacroCalendarProps) {
  if (isLoading) return <PanelSkeleton />;

  const groups = groupByDay(data);

  return (
    <Panel
      title="Macro Calendar (US)"
      action={
        data.length > 0 ? (
          <span className="text-xs font-mono tabnum text-fg-subtle">{data.length} events</span>
        ) : undefined
      }
      columns={
        data.length > 0 ? (
          <div className="flex items-center gap-3 h-7 px-4 bg-surface-2">
            <span className="label w-14 shrink-0">Time</span>
            <span className="label flex-1 min-w-0">Event</span>
            <span className="label w-20 shrink-0 text-right">Fcst</span>
            <span className="label w-20 shrink-0 text-right">Prev</span>
          </div>
        ) : undefined
      }
      footnote={
        data.length > 0
          ? `${horizonNote(data)} · Filled dot = high impact · Hollow dot = medium impact`
          : 'Filled dot = high impact · Hollow dot = medium impact'
      }
    >
      {/* A failed feed is not a quiet month — the two must not look the same. */}
      {isError ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          <span className="text-base">Calendar unavailable</span>
        </div>
      ) : data.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          {/* Past releases are filtered out, and the window runs a month ahead,
              so an empty list means the schedule itself is empty. */}
          <span className="text-base">No scheduled releases ahead</span>
        </div>
      ) : (
        <div>
          {/* Laid out as rows of cells rather than a table, because the day
              headings have to be sticky and a sticky `th` is not scoped to its
              `tbody` — its containing block is the whole table, so every heading
              that reached the top stayed pinned there and the stack of them bled
              a sliver of row between the column header and the current day. A
              plain block wrapper per day is a containing block, so each heading
              is pushed out by its own group the way it should be. */}
          {groups.map((group) => (
            <section key={group.date}>
              {/* Stops a scrollbar's width short of the right edge. The column
                  header above lives outside the scroller precisely because an
                  opaque full-width bar paints over macOS's overlay thumb; this
                  one has to scroll, so it buys the same clearance with a
                  margin instead. */}
              <h4 className="label sticky top-0 z-[1] mr-[var(--scrollbar-w)] px-4 py-1 bg-surface border-t border-line text-fg-muted">
                {formatDay(group.date)}
              </h4>
              {group.events.map((event, idx) => {
                const isHigh = event.impact === 'High';
                return (
                  <div
                    key={`${group.date}-${idx}`}
                    className="flex items-baseline gap-3 px-4 py-2 border-t border-line hover:bg-surface-2 transition-colors"
                  >
                    <span className="w-14 shrink-0 text-xs font-mono tabnum text-fg-subtle">
                      {event.time}
                    </span>
                    <span className="flex-1 min-w-0 flex items-baseline gap-2">
                      <span
                        className={`w-1.5 h-1.5 rounded-full shrink-0 translate-y-[-0.15em] ${
                          isHigh ? 'bg-warn' : 'border border-fg-subtle'
                        }`}
                      />
                      <span className={`text-base ${isHigh ? 'text-fg' : 'text-fg-muted'}`}>
                        {event.title}
                      </span>
                    </span>
                    <span className="w-20 shrink-0 text-right text-base font-mono tabnum text-fg-muted">
                      {event.forecast || '–'}
                    </span>
                    <span className="w-20 shrink-0 text-right text-base font-mono tabnum text-fg-subtle">
                      {event.previous || '–'}
                    </span>
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      )}
    </Panel>
  );
}
