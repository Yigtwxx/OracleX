'use client';

import { useState } from 'react';
import { ExternalLink } from 'lucide-react';
import type { LiveEvent, LiveStreamChannel } from '@/lib/api';
import StreamPlayer, { resolveSource } from '@/components/live/StreamPlayer';
import { formatDistance, formatElapsed, formatLocalTime, formatUtcTime } from '@/lib/live-format';

/**
 * How many rows the "up next" list carries.
 *
 * Five, because that is what fills the column beside a 36rem player without
 * overflowing it. It was three when the player was 22rem; leaving it there
 * after the frame grew opened a band of dead space between this list and the
 * channel chips pinned below it.
 */
const NEXT_UP_COUNT = 5;

interface NowHeroProps {
  liveEvents: LiveEvent[];
  /** The scheduled queue, soonest first — the hero shows the head of it. */
  upcoming: LiveEvent[];
  selectedEvent: LiveEvent | null;
  channels: LiveStreamChannel[];
  streamsLoading: boolean;
  now: number;
  onSelect: (event: LiveEvent) => void;
}

/**
 * The top of the page: what is on air, beside what it is.
 *
 * This band is always present, which is the point — a hero that appeared only
 * during a press conference would leave the page headless for most of the day
 * and move everything below it whenever something started. When nothing is
 * live it answers the next question instead ("what's next, and when"), and the
 * player falls back to a rolling market channel.
 */
export default function NowHero({
  liveEvents,
  upcoming,
  selectedEvent,
  channels,
  streamsLoading,
  now,
  onSelect,
}: NowHeroProps) {
  const [pinnedKey, setPinnedKey] = useState<string | null>(null);

  // What the headline describes: the row the user picked if it is live,
  // otherwise the first live event, otherwise nothing.
  const headline =
    selectedEvent && selectedEvent.status === 'live' ? selectedEvent : (liveEvents[0] ?? null);
  const nextUp = upcoming.slice(0, NEXT_UP_COUNT);
  const { caption, watchUrl } = resolveSource(channels, selectedEvent, pinnedKey);
  const probeBlocked = channels.length > 0 && channels.every((channel) => channel.probe_failed);

  return (
    // The player takes the larger share of the hero: it is the only thing on
    // the page that has to be watched rather than read, and at 22rem the frame
    // was smaller than the text beside it, which inverted what the band is for.
    // The text column keeps `minmax(0,1fr)` so it yields first as the viewport
    // narrows.
    <div className="surface p-3 grid grid-cols-1 md:grid-cols-[minmax(0,36rem)_minmax(0,1fr)] gap-4">
      <StreamPlayer
        channels={channels}
        selectedEvent={selectedEvent}
        pinnedKey={pinnedKey}
        isLoading={streamsLoading}
      />

      <div className="flex flex-col min-w-0">
        {headline ? (
          <>
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-down-bg text-down text-2xs uppercase tracking-wide">
                <span className="w-1 h-1 rounded-full bg-down live-indicator" />
                Live
              </span>
              <span className="text-xs font-mono tabnum text-fg-subtle">
                {formatElapsed(headline.starts_at, now)}
              </span>
            </div>
            <h2 className="mt-1.5 text-base font-semibold text-fg">{headline.title}</h2>
            <p className="text-sm text-fg-muted">
              {[headline.speaker, headline.detail].filter(Boolean).join(' · ') || '—'}
            </p>
            <p className="mt-0.5 text-xs font-mono tabnum text-fg-subtle">
              {formatLocalTime(headline.starts_at)}
              <span className="ml-1.5 text-2xs">{formatUtcTime(headline.starts_at)}</span>
              {headline.country && <span className="ml-2">{headline.country}</span>}
            </p>
          </>
        ) : (
          <div className="flex items-center gap-2">
            <span className="px-1.5 py-0.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle">
              Off air
            </span>
            <span className="text-sm text-fg-muted">Nothing scheduled is running right now.</span>
          </div>
        )}

        {/* Up next, in both states. When something is live this is what to
            watch for after it; when nothing is, it is the whole answer — and it
            is what keeps this half of the hero from being a blank rectangle for
            most of the trading day. */}
        <div className="mt-3">
          <span className="label">Up next</span>
          {nextUp.length === 0 ? (
            <p className="mt-1 text-sm text-fg-muted">Nothing scheduled in this window.</p>
          ) : (
            <div className="mt-1 divide-y divide-line border-y border-line">
              {nextUp.map((event) => (
                <button
                  key={event.id}
                  onClick={() => onSelect(event)}
                  aria-pressed={event.id === selectedEvent?.id}
                  className={`w-full px-1 py-1.5 flex items-baseline gap-2.5 text-left transition-colors ${
                    event.id === selectedEvent?.id ? 'bg-surface-2' : 'hover:bg-surface-2'
                  }`}
                >
                  <span className="w-11 shrink-0 text-xs font-mono tabnum text-fg">
                    {event.time_confirmed ? formatLocalTime(event.starts_at) : '—'}
                  </span>
                  <span className="min-w-0 flex-1 text-sm text-fg truncate">
                    {event.title}
                    {event.speaker && (
                      <span className="ml-1.5 text-xs text-fg-subtle">{event.speaker}</span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs font-mono tabnum text-fg-subtle">
                    {event.time_confirmed
                      ? (formatDistance(event.starts_at, now) ?? '')
                      : (event.location ?? '')}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Channel picker. Pushed to the bottom so the blocks above stay pinned
            to the top edge whichever state is rendering. */}
        <div className="mt-auto pt-3 space-y-1.5">
          <div
            role="group"
            aria-label="Choose a broadcast channel"
            className="flex flex-wrap gap-1"
          >
            {channels.map((channel) => (
              <button
                key={channel.key}
                aria-pressed={pinnedKey === channel.key}
                onClick={() => setPinnedKey(pinnedKey === channel.key ? null : channel.key)}
                className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-xs transition-colors ${
                  pinnedKey === channel.key
                    ? 'bg-surface-2 border-line-strong text-fg'
                    : 'border-line text-fg-muted hover:text-fg hover:border-line-strong'
                }`}
              >
                <span
                  className={`w-1 h-1 rounded-full ${
                    channel.is_live ? 'bg-down live-indicator' : 'bg-fg-subtle'
                  }`}
                />
                {channel.name}
              </button>
            ))}
          </div>

          <div className="flex items-start justify-between gap-3">
            <p className="text-xs text-fg-subtle min-w-0 truncate">
              {probeBlocked
                ? 'Stream detection is unavailable — the dots above may be wrong, but the player still works.'
                : (caption ?? '—')}
            </p>
            {watchUrl && (
              <a
                href={watchUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 flex items-center gap-1 text-xs text-fg-subtle hover:text-fg transition-colors"
              >
                YouTube
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
