'use client';

import { ExternalLink } from 'lucide-react';
import type { LiveEvent } from '@/lib/api';
import { formatDistance, formatLocalTime, formatUtcTime, impactDotClass } from '@/lib/live-format';

interface EventRowProps {
  event: LiveEvent;
  /** Shared page clock — see `useNow`. */
  now: number;
  isSelected: boolean;
  onSelect: (event: LiveEvent) => void;
}

/**
 * One calendar row.
 *
 * Reads left to right the way a trader scans it: when, where, how much it
 * matters, what it is, and what the number is expected to be.
 */
export default function EventRow({ event, now, isSelected, onSelect }: EventRowProps) {
  const isLive = event.status === 'live';
  const isEnded = event.status === 'ended';
  // A row whose source published only a day gets its session window instead of
  // a countdown. Earnings are the case that matters: Nasdaq says "before open",
  // and anchoring that to 08:30 to sort it does not make "in 37m" true.
  const distance = isLive
    ? null
    : event.time_confirmed
      ? formatDistance(event.starts_at, now)
      : event.location;

  return (
    <article
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      onClick={() => onSelect(event)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(event);
        }
      }}
      className={`px-4 py-2.5 flex items-start gap-3 cursor-pointer transition-colors ${
        isSelected ? 'bg-surface-2' : 'hover:bg-surface-2'
      } ${isEnded ? 'opacity-55' : ''}`}
    >
      {/* Time. Local is the figure being read; UTC sits under it because every
          source this tab aggregates publishes in UTC and the two have to be
          reconcilable without arithmetic. */}
      <div className="w-14 shrink-0 text-right">
        <div className="text-base font-mono tabnum text-fg">
          {event.time_confirmed ? formatLocalTime(event.starts_at) : '—'}
        </div>
        <div className="text-2xs font-mono tabnum text-fg-subtle">
          {event.time_confirmed ? formatUtcTime(event.starts_at) : 'TBD'}
        </div>
      </div>

      <span
        className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${impactDotClass(event.impact)}`}
        title={`${event.impact} impact`}
      />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          {isLive && (
            <span className="flex items-center gap-1 px-1.5 py-px rounded bg-down-bg text-down text-2xs uppercase tracking-wide">
              <span className="w-1 h-1 rounded-full bg-down live-indicator" />
              Live
            </span>
          )}
          {event.country && (
            <span className="text-2xs font-mono text-fg-subtle">{event.country}</span>
          )}
          <span className="text-base text-fg">{event.title}</span>
        </div>

        {(event.speaker || event.detail) && (
          <div className="text-xs text-fg-subtle truncate">{event.speaker ?? event.detail}</div>
        )}

        {(event.forecast || event.previous) && (
          <div className="mt-0.5 flex items-center gap-3 text-xs font-mono tabnum text-fg-muted">
            {event.forecast && (
              <span>
                <span className="text-fg-subtle">fcst </span>
                {event.forecast}
              </span>
            )}
            {event.previous && (
              <span>
                <span className="text-fg-subtle">prev </span>
                {event.previous}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 flex items-center gap-2 text-xs text-fg-subtle">
        {distance && <span className="font-mono tabnum">{distance}</span>}
        {event.watch_url && (
          <a
            href={event.watch_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            aria-label={`Open the broadcast for ${event.title}`}
            className="text-fg-subtle hover:text-fg transition-colors"
          >
            <ExternalLink className="w-3 h-3" />
          </a>
        )}
      </div>
    </article>
  );
}
