'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Pizza } from 'lucide-react';
import type { PizzaIndexHour, PizzaVenue } from '@/lib/api';
import { usePizzaIndex } from '@/hooks/queries';
import {
  UNKNOWN,
  dialPosition,
  formatIndex,
  hasReading,
  ratioColor,
  statusCaption,
  statusColor,
  statusTone,
} from '@/lib/pizza-index';

/**
 * The Pentagon Pizza Index, as a header badge.
 *
 * It used to be a panel on Macro and a card on Home and Overview — three
 * renderings of one number, the largest of them taller than the priced
 * instruments it sat under. This is a novelty gauge, and the size of a surface
 * is a claim about how much it matters; a strip in the chrome is the honest
 * one. Living in the header also means it is on every tab instead of only the
 * three that happened to import it.
 *
 * The badge is the reading. The panel behind it is the evidence: the shared 24h
 * the index is a median of, then the six venues that median came from, each with
 * its own 24h on the same hour grid so a reader can see which venue is moving
 * the number.
 *
 * Opens on hover for a pointer and on click for everything else, matching
 * `LiveStatusBadge` beside it — hover alone strands touch users, click alone
 * makes a glanceable reading cost a tap.
 */
export default function PizzaIndexBadge() {
  const { data, isLoading } = usePizzaIndex();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on Escape and on an outside click, so a panel opened by tap is not
  // stuck open on a device that never fires mouseleave.
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onPointerDown = (e: PointerEvent): void => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open]);

  // Rendered as an empty reading rather than hidden. A badge that disappears
  // when the scrape fails looks like a feature that was never there, which is
  // the one thing an outage must not be mistaken for.
  const readable = data ? hasReading(data.status) : false;
  const reading = isLoading ? '···' : readable ? formatIndex(data!.index) : UNKNOWN;

  return (
    <div
      ref={containerRef}
      className="relative shrink-0"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Pentagon Pizza Index"
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-line hover:bg-surface-2 transition-colors"
      >
        <Pizza className="w-3.5 h-3.5 shrink-0 text-[var(--pizza)]" />
        <span
          className={`text-xs font-mono tabnum ${data ? statusTone(data.status) : 'text-fg-subtle'}`}
        >
          {reading}
        </span>
        {data?.stale && (
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--warn)]" title="Replayed from cache" />
        )}
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 top-full mt-1 w-80 bg-surface border border-line rounded-lg shadow-lg z-50 overflow-hidden"
        >
          {data ? <PanelBody data={data} /> : <div className="h-40 shimmer" />}
        </div>
      )}
    </div>
  );
}

/** The panel's contents, once there is a payload to render. */
function PanelBody({ data }: { data: NonNullable<ReturnType<typeof usePizzaIndex>['data']> }) {
  const readable = hasReading(data.status);
  // Venues with nothing to plot still get a row — a list that silently shows
  // four of six venues is misreporting its own sample size — but no bars.
  const venues = data.venues;

  return (
    <>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line">
        <Pizza className="w-3.5 h-3.5 shrink-0 text-[var(--pizza)]" />
        <h3 className="label truncate">Pentagon Pizza Index</h3>
        {data.stale && (
          <span
            title="Source unavailable — showing the last known reading"
            className="ml-auto px-1.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle"
          >
            Stale
          </span>
        )}
      </div>

      {/* The reading, then the single shared trend it was derived from. */}
      <div className="px-3 py-2.5 border-b border-line">
        <div className="flex items-baseline justify-center gap-2">
          <span className={`text-lg font-mono tabnum ${statusTone(data.status)}`}>
            {readable ? formatIndex(data.index) : UNKNOWN}
          </span>
          <span
            className="text-2xs uppercase tracking-wider"
            style={{ color: statusColor(data.status) }}
          >
            {data.label}
          </span>
        </div>

        <div className="mt-2">
          <HistoryBars history={data.history} />
        </div>

        <p className="mt-1.5 text-2xs text-fg-subtle text-center">
          {statusCaption(data.status, data.venues_used)}
        </p>
      </div>

      {/* Per-venue. Capped in height rather than in count: dropping the tail
          would hide exactly the venue an unusual reading came from. */}
      <div className="max-h-56 overflow-y-auto">
        {venues.length === 0 ? (
          <p className="px-3 py-3 text-2xs text-fg-subtle">No venues reporting.</p>
        ) : (
          venues.map((venue) => <VenueRow key={venue.place_id} venue={venue} />)
        )}
      </div>

      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-t border-line text-2xs text-fg-subtle">
        <span>
          An OSINT novelty ·{' '}
          <a
            href={data.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-fg-muted transition-colors"
          >
            {data.source}
          </a>
        </span>
        <span className="font-mono tabnum shrink-0">
          {new Date(data.as_of).toLocaleTimeString('en-GB')}
        </span>
      </div>
    </>
  );
}

/**
 * The last 24 hours, one bar per local hour.
 *
 * Unscored hours render as an empty slot rather than being skipped: closing the
 * gap would draw a continuous trend across hours in which nothing was measured,
 * which is the one thing this reading is built not to do.
 */
function HistoryBars({ history }: { history: PizzaIndexHour[] }) {
  if (!history.length) return null;

  return (
    <div className="flex items-end gap-px h-8">
      {history.map((hour) => (
        <Bar
          key={hour.hour_et}
          hourEt={hour.hour_et}
          ratio={hour.index}
          title={
            hour.index === null
              ? `unscored (${hour.venues_used} venue${hour.venues_used === 1 ? '' : 's'})`
              : `${formatIndex(hour.index)} (${hour.venues_used} venues)`
          }
        />
      ))}
    </div>
  );
}

/** One hour's bar, shared by both charts so they cannot scale differently. */
function Bar({ hourEt, ratio, title }: { hourEt: string; ratio: number | null; title: string }) {
  const position = dialPosition(ratio);
  // Bars grow from the floor; a 1.0x reading lands at half height, so
  // taller-than-half is busier than usual and shorter is quieter.
  const height = position === null ? 0 : ((position + 1) / 2) * 100;
  const label = new Date(hourEt).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
  });

  return (
    <div
      className="flex-1 h-full flex items-end bg-surface-2 rounded-[1px] overflow-hidden"
      title={`${label} ET — ${title}`}
    >
      {ratio !== null && (
        <div
          className="w-full rounded-[1px]"
          style={{ height: `${Math.max(height, 6)}%`, background: ratioColor(ratio) }}
        />
      )}
    </div>
  );
}

/**
 * One venue: its own 24h beside its live reading.
 *
 * The bars sit on the grid the aggregate above uses — the server pads every
 * venue to it — so a venue that was shut overnight renders empty slots there
 * rather than compressing its night away and shifting its morning left.
 *
 * A venue that did not contribute says why in place of its ratio. That is the
 * difference between "closed" and "we could not see it", and a blank cell says
 * neither.
 */
function VenueRow({ venue }: { venue: PizzaVenue }) {
  const contributed = venue.ratio !== null;
  const hasBars = venue.history.some((hour) => hour.ratio !== null);

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-2/60 transition-colors"
      title={
        contributed
          ? `${venue.current} now / ${venue.baseline} usual${venue.address ? ` · ${venue.address}` : ''}`
          : (venue.address ?? undefined)
      }
    >
      <span className="text-xs text-fg truncate flex-1 min-w-0">{venue.name}</span>

      {hasBars && (
        <div className="flex items-end gap-px h-4 w-20 shrink-0">
          {venue.history.map((hour) => (
            <Bar
              key={hour.hour_et}
              hourEt={hour.hour_et}
              ratio={hour.ratio}
              title={hour.ratio === null ? 'no reading' : formatIndex(hour.ratio)}
            />
          ))}
        </div>
      )}

      {contributed ? (
        <span className="text-xs font-mono tabnum text-fg shrink-0 w-12 text-right">
          {formatIndex(venue.ratio)}
        </span>
      ) : (
        <span className="text-2xs uppercase tracking-wide text-fg-subtle shrink-0 w-12 text-right truncate">
          {venue.is_closed ? 'Closed' : (venue.excluded_reason ?? 'n/a')}
        </span>
      )}
    </div>
  );
}
