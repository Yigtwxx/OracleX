'use client';

import { useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { useLiveEvents, useLiveStreamers, useLiveStreams, useLiveTape } from '@/hooks/queries';
import { useNow } from '@/hooks/useNow';
import type { LiveEvent } from '@/lib/api';
import EventCalendar, { type KindFilter } from '@/components/live/EventCalendar';
import HeadlineTape from '@/components/live/HeadlineTape';
import NowHero from '@/components/live/NowHero';
import StreamerBoard from '@/components/live/StreamerBoard';
import { localZoneLabel } from '@/lib/live-format';

/**
 * The Live tab: what is happening right now, what is about to, and the wire
 * copy running alongside both.
 *
 * The page owns all four queries and every piece of selection state; the panels
 * below take props and nothing else. That is what lets clicking a calendar row
 * change what the hero plays without either component knowing the other exists.
 */
export default function LivePage() {
  const [filter, setFilter] = useState<KindFilter>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const events = useLiveEvents();
  const streams = useLiveStreams();
  const tape = useLiveTape();
  // The streamer board sits beside the calendar rather than behind a tab, so
  // this can no longer be gated on being looked at — every open of the page
  // costs a probe of twenty channel pages server-side. The ten-minute cache on
  // both ends is what keeps a tab left open from paying that repeatedly.
  const streamers = useLiveStreamers();

  // One clock for the whole page. Every countdown and elapsed timer below reads
  // this rather than starting an interval of its own.
  const now = useNow();

  const liveEvents = events.data?.live ?? [];

  // Resolved against the payload rather than held as an object: a stored copy
  // would keep claiming an event is live after the server has ended it.
  const selectedEvent = useMemo<LiveEvent | null>(() => {
    if (!selectedId || !events.data) return null;
    const all = [...events.data.live, ...events.data.upcoming, ...events.data.recent];
    return all.find((event) => event.id === selectedId) ?? null;
  }, [selectedId, events.data]);

  // Live first, then the week ahead. `recent` is deliberately left out of the
  // calendar: it answers "what is coming", and the tape covers what landed.
  const calendarRows = useMemo(
    () => (events.data ? [...events.data.live, ...events.data.upcoming] : []),
    [events.data]
  );

  const upcoming = events.data?.upcoming ?? [];
  const channels = streams.data?.channels ?? [];

  const onSelect = (event: LiveEvent) =>
    setSelectedId((current) => (current === event.id ? null : event.id));

  const refreshAll = () => {
    events.refetch();
    streams.refetch();
    tape.refetch();
    streamers.refetch();
  };

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4">
      <div className="max-w-[1600px] mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-lg font-semibold text-fg">Live</h1>
            <p className="text-base text-fg-muted">
              Central bank decisions, policy speeches and macro prints — as they happen. Times in{' '}
              {localZoneLabel()}.
            </p>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {/* The server's own `as_of`, not the client's fetch time — a cached
                payload replayed after an upstream failure must not be stamped
                with the moment the browser asked for it. */}
            {events.data?.as_of && (
              <span className="flex items-center gap-2">
                {events.data.stale && (
                  <span
                    title="Upstream unavailable — showing the last known calendar"
                    className="px-1.5 py-0.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle"
                  >
                    Stale
                  </span>
                )}
                <span className="text-xs font-mono tabnum text-fg-subtle">
                  {new Date(events.data.as_of).toLocaleTimeString('en-GB')}
                </span>
              </span>
            )}
            <button
              onClick={refreshAll}
              aria-label="Refresh the live board"
              className="p-1.5 bg-surface border border-line rounded-md text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${events.isFetching ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* A failed calendar is reported, not rendered as an empty page. Blank
            panels would read as "nothing is scheduled and nothing is on air",
            which is a claim about the world rather than a gap in the data. */}
        {events.isError ? (
          <div className="surface p-6 text-center">
            <p className="text-base text-fg">The live calendar is unavailable.</p>
            <p className="mt-1 text-sm text-fg-subtle">
              Neither the economic calendar nor the Federal Reserve schedule could be reached.
            </p>
            <button
              onClick={() => events.refetch()}
              className="mt-3 px-3 py-1.5 bg-surface-2 border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              Try again
            </button>
          </div>
        ) : (
          // No `items-start`: the default stretch is what lets the tape match
          // the left column's height on its own, instead of being handed a
          // computed one that drifts the moment the hero changes size.
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_20rem] gap-3">
            {/* Left column: the hero, then the two boards side by side. */}
            <div className="space-y-3 min-w-0">
              <NowHero
                liveEvents={liveEvents}
                upcoming={upcoming}
                selectedEvent={selectedEvent}
                channels={channels}
                streamsLoading={streams.isLoading}
                now={now}
                onSelect={onSelect}
              />

              {/* The split waits for 2xl rather than lg. Once the right rail has
                  taken its 20rem, an lg viewport leaves each of these about
                  330px — narrower than a calendar row's five columns can be read
                  in. Below the breakpoint they stack, which keeps both visible
                  without either being squeezed.

                  Both boards carry the same height at every breakpoint rather
                  than only at the split. A height that applied only at 2xl left
                  them at `h-full` of an auto-height parent everywhere else,
                  which is no constraint at all: the calendar runs to December,
                  so the panel grew to 2,800px and took the page with it instead
                  of scrolling inside its own frame. */}
              <div className="grid grid-cols-1 2xl:grid-cols-2 gap-3">
                <div className="h-[34rem]">
                  <EventCalendar
                    events={calendarRows}
                    isLoading={events.isLoading}
                    now={now}
                    filter={filter}
                    onFilterChange={setFilter}
                    selectedId={selectedId}
                    onSelect={onSelect}
                  />
                </div>
                <div className="h-[34rem]">
                  <StreamerBoard
                    streamers={streamers.data?.streamers ?? []}
                    liveCount={streamers.data?.live_count ?? 0}
                    isLoading={streamers.isLoading}
                  />
                </div>
              </div>
            </div>

            {/* Right rail: the tape. It stretches to the left column's height
                from `lg` up, where the two are side by side; stacked below that
                there is nothing to match, so it takes a bounded height of its
                own rather than running to the length of the wire. */}
            <div className="h-[30rem] lg:h-auto">
              <HeadlineTape
                items={tape.data?.items ?? []}
                isLoading={tape.isLoading}
                warming={tape.data?.warming ?? false}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
