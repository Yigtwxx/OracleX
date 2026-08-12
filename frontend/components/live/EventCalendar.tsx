'use client';

import { useMemo } from 'react';
import type { LiveEvent, LiveEventKind } from '@/lib/api';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';
import EventRow from '@/components/live/EventRow';
import { KIND_LABELS, dayGroup, formatDayLabel } from '@/lib/live-format';

/** `null` is the "All" chip — kept in the same union so one map drives the strip. */
type KindFilter = LiveEventKind | null;

const FILTERS: { value: KindFilter; label: string }[] = [
  { value: null, label: 'All' },
  { value: 'central_bank', label: KIND_LABELS.central_bank },
  { value: 'political', label: KIND_LABELS.political },
  { value: 'macro_data', label: KIND_LABELS.macro_data },
  { value: 'corporate', label: KIND_LABELS.corporate },
];

interface EventCalendarProps {
  events: LiveEvent[];
  isLoading: boolean;
  now: number;
  filter: KindFilter;
  onFilterChange: (filter: KindFilter) => void;
  selectedId: string | null;
  onSelect: (event: LiveEvent) => void;
}

/**
 * The week ahead, grouped by day.
 *
 * Grouping rather than a flat list because the first question asked of this
 * panel is "what is left today", and a flat list answers it only by reading
 * dates off every row.
 */
export default function EventCalendar({
  events,
  isLoading,
  now,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
}: EventCalendarProps) {
  const groups = useMemo(() => {
    const visible = filter ? events.filter((event) => event.kind === filter) : events;
    const today: LiveEvent[] = [];
    const tomorrow: LiveEvent[] = [];
    const later = new Map<string, LiveEvent[]>();

    for (const event of visible) {
      const group = dayGroup(event.starts_at, now);
      if (group === 'today') {
        today.push(event);
      } else if (group === 'tomorrow') {
        tomorrow.push(event);
      } else {
        const label = formatDayLabel(event.starts_at);
        const bucket = later.get(label);
        if (bucket) bucket.push(event);
        else later.set(label, [event]);
      }
    }
    return { today, tomorrow, later, total: visible.length };
    // `now` is a ticking clock, so it is deliberately not a dependency: the day
    // an event falls under changes at midnight, not once a second, and
    // regrouping the whole list every tick would rebuild it 86,400 times a day.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events, filter]);

  if (isLoading) return <PanelSkeleton />;

  const sections: { label: string; rows: LiveEvent[] }[] = [
    { label: 'Today', rows: groups.today },
    { label: 'Tomorrow', rows: groups.tomorrow },
    ...Array.from(groups.later, ([label, rows]) => ({ label, rows })),
  ];

  return (
    <Panel
      title="Calendar"
      action={
        <div role="group" aria-label="Filter events by kind" className="flex items-center gap-1">
          {FILTERS.map(({ value, label }) => (
            <button
              key={label}
              aria-pressed={filter === value}
              onClick={() => onFilterChange(value)}
              className={`px-2 py-0.5 rounded-md text-xs transition-colors ${
                filter === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      }
    >
      {groups.total === 0 ? (
        /* A filtered-to-nothing list keeps its filter strip above it, so the
           way back is visible from the empty state itself. */
        <div className="px-4 py-10 text-center">
          <p className="text-base text-fg-muted">No scheduled events match this filter.</p>
          <p className="mt-1 text-xs text-fg-subtle">
            The calendar covers the current week plus whatever the Fed has published beyond it.
          </p>
        </div>
      ) : (
        sections
          .filter((section) => section.rows.length > 0)
          .map((section) => (
            <section key={section.label}>
              <h4 className="label sticky top-0 z-10 px-4 py-1.5 bg-surface border-y border-line">
                {section.label}
              </h4>
              <div className="divide-y divide-line">
                {section.rows.map((event) => (
                  <EventRow
                    key={event.id}
                    event={event}
                    now={now}
                    isSelected={event.id === selectedId}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            </section>
          ))
      )}
    </Panel>
  );
}

export type { KindFilter };
