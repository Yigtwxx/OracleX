'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Pizza, Siren } from 'lucide-react';
import type { PizzaIndexHour, PizzaVenue } from '@/lib/api';
import { useNehIndex, usePizzaIndex } from '@/hooks/queries';
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
import * as neh from '@/lib/neh-index';

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

      <NehStrip />

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

/**
 * The Nothing Ever Happens Index, as the last strip of the panel.
 *
 * It sits here rather than in a badge of its own because it is the same kind of
 * claim from the same publisher: an OSINT novelty about how close something is
 * to happening. Two novelty badges in the chrome would be twice the furniture
 * for no more information, and the header is the surface this app is most
 * careful about spending.
 *
 * Compact on purpose — a reading, the band it fell in, and the one market that
 * set it. The full basket is a page on the source, and this is a link to it,
 * not a reimplementation of it.
 *
 * Rendered inside the open panel, which is what keeps `useNehIndex` from
 * polling prediction markets for readers who never hover.
 */
function NehStrip() {
  const { data, isLoading } = useNehIndex();

  const readable = data ? neh.hasReading(data.status) : false;
  const position = readable ? neh.bandPosition(data!.index) : null;
  const tone = data ? neh.statusTone(data.status) : 'text-fg-subtle';

  return (
    <div className="px-3 py-2 border-t border-line">
      <div className="flex items-center gap-2">
        <Siren className="w-3 h-3 shrink-0 text-fg-subtle" />
        {/* The strip is a summary of a page, so the title is the way to that
            page. The panel footer's link goes to the pizza source instead, and
            sending both readings to one URL would strand this one. */}
        {data ? (
          <a
            href={data.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="label truncate hover:text-fg-muted transition-colors"
          >
            Nothing Ever Happens
          </a>
        ) : (
          <span className="label truncate">Nothing Ever Happens</span>
        )}
        <span className={`ml-auto text-xs font-mono tabnum shrink-0 ${tone}`}>
          {isLoading ? '···' : readable ? neh.formatIndex(data!.index) : neh.UNKNOWN}
        </span>
      </div>

      {/* One quarter of the track per band, with the marker on it. Each segment
          carries its own colour at full strength once the reading has reached
          it, so the track reads as a filled gauge and not as four buttons. */}
      <div className="relative mt-1.5 flex items-center gap-px">
        {neh.BANDS.map((band, i) => {
          const reached = position !== null && position >= i * 25;
          return (
            <div
              key={band.status}
              title={band.label}
              className="h-1 flex-1 first:rounded-l-sm last:rounded-r-sm"
              style={{
                background: neh.statusColor(band.status),
                opacity: reached ? 0.9 : 0.2,
              }}
            />
          );
        })}
        {position !== null && (
          <div
            className="absolute top-1/2 h-2.5 w-0.5 rounded-full bg-fg pointer-events-none"
            style={{ left: `${position}%`, transform: 'translate(-50%, -50%)' }}
          />
        )}
      </div>

      <p className="mt-1.5 text-2xs text-fg-subtle truncate">
        {isLoading ? (
          'Reading the basket…'
        ) : data && readable && data.top ? (
          <>
            <span className={tone}>{data.label}</span>
            {' · '}
            {data.top.label} {neh.formatProbability(data.top.probability)}
          </>
        ) : (
          'Prediction markets could not be read'
        )}
      </p>
    </div>
  );
}
