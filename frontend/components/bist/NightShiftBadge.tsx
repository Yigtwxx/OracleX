'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Moon, Siren } from 'lucide-react';

import { useBistNightShift } from '@/hooks/useBist';
import type { NightShiftDay, NightShiftHistoryDay, NightShiftSource } from '@/lib/bist-api';
import {
  MUKERRER_BANDS,
  UNKNOWN,
  dialPosition,
  formatIndex,
  hasReading,
  markerShift,
  mukerrerCaption,
  mukerrerColor,
  mukerrerFill,
  mukerrerPosition,
  mukerrerState,
  padHistory,
  ratioColor,
  statusCaption,
  statusColor,
  statusTone,
} from '@/lib/night-shift';

/**
 * Gece Mesaisi Endeksi, as a header badge.
 *
 * Sits in the slot `PizzaIndexBadge` occupies on the crypto realm, and is
 * deliberately its twin rather than its replacement: the pizza gauge is
 * untouched and still the only thing that renders on `/home` and every other
 * global tab. `Navigation` picks one by realm, so the two never appear
 * together and the header keeps exactly one novelty gauge.
 *
 * The badge is the reading. The panel behind it is the evidence: the shared
 * fortnight the index is a median of, then the sources that median came from,
 * each with its own fortnight on the same day grid so a reader can see which
 * one is moving the number.
 *
 * Opens on hover for a pointer and on click for everything else, matching
 * `LiveStatusBadge` beside it — hover alone strands touch users, click alone
 * makes a glanceable reading cost a tap.
 */
export default function NightShiftBadge() {
  const { data, isLoading } = useBistNightShift();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on Escape and on an outside click, so a panel opened by tap is not
  // stuck open on a device that never fires mouseleave.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open]);

  // Rendered as an empty reading rather than hidden. A badge that disappears
  // when the sources fail looks like a feature that was never there, which is
  // the one thing an outage must not be mistaken for.
  const readable = data ? hasReading(data.status) : false;
  const reading = isLoading ? '···' : readable ? formatIndex(data!.index) : UNKNOWN;

  return (
    <div
      ref={containerRef}
      // `lang="tr"` is load-bearing, not metadata — the same reason
      // `BistPageShell` carries it. CSS `text-transform: uppercase` is
      // language-sensitive, and `.label` uppercases every heading in this
      // panel: without the tag the browser applies the default Latin rule and
      // renders "Gece Mesaisi Endeksi" as "MESAISI ENDEKSI", turning a dotted
      // `i` into a dotless `I` — a different letter in Turkish. The badge sits
      // in the app chrome, outside the shell that would otherwise supply it.
      lang="tr"
      className="relative shrink-0"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Gece Mesaisi Endeksi"
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 transition-colors hover:bg-surface-2"
      >
        <Moon className="h-3.5 w-3.5 shrink-0 text-[var(--gazette)]" />
        <span
          className={`tabnum font-mono text-xs ${data ? statusTone(data.status) : 'text-fg-subtle'}`}
        >
          {reading}
        </span>
        {/* An extra edition today is the one event this gauge exists for, and
            it is worth a mark on the badge rather than only inside the panel. */}
        {data?.mukerrer_today && (
          <Siren className="h-3 w-3 shrink-0 text-[var(--warn)]" aria-label="Bugün mükerrer sayı" />
        )}
        {data?.stale && (
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--warn)]" title="Önbellekten okundu" />
        )}
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 top-full z-50 mt-1 w-80 overflow-hidden rounded-lg border border-line bg-surface shadow-lg"
        >
          {data ? <PanelBody data={data} /> : <div className="shimmer h-40" />}
        </div>
      )}
    </div>
  );
}

/** The panel's contents, once there is a payload to render. */
function PanelBody({ data }: { data: NonNullable<ReturnType<typeof useBistNightShift>['data']> }) {
  const readable = hasReading(data.status);

  return (
    <>
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Moon className="h-3.5 w-3.5 shrink-0 text-[var(--gazette)]" />
        <h3 className="label truncate">Gece Mesaisi Endeksi</h3>
        {data.stale && (
          <span
            title="Kaynaklara ulaşılamadı — son bilinen okuma gösteriliyor"
            className="ml-auto rounded border border-line px-1.5 text-2xs uppercase tracking-wide text-fg-subtle"
          >
            Eski
          </span>
        )}
      </div>

      {/* The reading, then the single shared trend it was derived from. */}
      <div className="border-b border-line px-3 py-2.5">
        <div className="flex items-baseline justify-center gap-2">
          <span className={`tabnum font-mono text-lg ${statusTone(data.status)}`}>
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

        <p className="mt-1.5 text-center text-2xs text-fg-subtle">
          {statusCaption(data.status, data.sources_used)}
        </p>
      </div>

      {/* Per source. Capped in height rather than in count: dropping the tail
          would hide exactly the source an unusual reading came from. */}
      <div className="max-h-56 overflow-y-auto">
        {data.sources.length === 0 ? (
          <p className="px-3 py-3 text-2xs text-fg-subtle">Ölçülebilen kaynak yok.</p>
        ) : (
          data.sources.map((source) => <SourceRow key={source.key} source={source} />)
        )}
      </div>

      {/* Below the source rows, where the Nothing Ever Happens strip sits in
          the pizza panel. The order is the argument: the rows above are the
          continuous readings the index is a median of, and this is the rare
          event they cannot express — it belongs after them rather than
          interrupting them. */}
      <MukerrerStrip
        days={data.days_since_mukerrer}
        today={data.mukerrer_today}
        last={data.last_mukerrer}
      />

      <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-1.5 text-2xs text-fg-subtle">
        <span>
          Eşzamanlı gösterge ·{' '}
          <a
            href={data.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline transition-colors hover:text-fg-muted"
          >
            {data.source}
          </a>
        </span>
        <span className="tabnum shrink-0 font-mono">
          {new Date(data.as_of).toLocaleTimeString('tr-TR', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>
    </>
  );
}

/**
 * The last fortnight, one bar per day.
 *
 * Unscored days render as an empty slot rather than being skipped: closing the
 * gap would draw a continuous trend across days nothing was measured on, which
 * is the one thing this reading is built not to do.
 */
function HistoryBars({ history }: { history: NightShiftHistoryDay[] }) {
  if (!history.length) return null;

  return (
    <div className="flex h-8 items-end gap-px">
      {history.map((day) => (
        <Bar
          key={day.day}
          day={day.day}
          ratio={day.index}
          title={
            day.index === null
              ? `ölçülemedi (${day.sources_used} kaynak)`
              : `${formatIndex(day.index)} (${day.sources_used} kaynak)`
          }
        />
      ))}
    </div>
  );
}

/**
 * One day's bar, shared by both charts so they cannot scale differently.
 *
 * `day` is null for a slot before a source's record begins. It still draws, so
 * every row keeps the same fourteen positions and the same axis.
 */
function Bar({ day, ratio, title }: { day: string | null; ratio: number | null; title: string }) {
  const position = dialPosition(ratio);
  // Bars grow from the floor; a 1,0× reading lands at half height, so
  // taller-than-half is busier than usual and shorter is quieter.
  const height = position === null ? 0 : ((position + 1) / 2) * 100;
  const label = day
    ? new Date(day).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })
    : null;

  return (
    <div
      className="flex h-full flex-1 items-end overflow-hidden rounded-[1px] bg-surface-2"
      title={label ? `${label} — ${title}` : title}
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
 * One source: its own fortnight beside its live reading.
 *
 * The bars sit on the grid the aggregate above uses, so a source that could not
 * be measured on some day renders an empty slot there rather than compressing
 * its gap away and shifting the rest of its row left.
 *
 * A source that did not contribute says so in place of its ratio. That is the
 * difference between "measured and ordinary" and "no baseline to divide by",
 * and a blank cell says neither.
 */
function SourceRow({ source }: { source: NightShiftSource }) {
  const contributed = source.ratio !== null;

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 transition-colors hover:bg-surface-2/60"
      title={source.detail}
    >
      <span className="min-w-0 flex-1 truncate text-xs text-fg">{source.name}</span>

      {/* Always drawn, even when not one day of the fortnight could be scored.
          Dropping the grid was the bug this replaced: the row lost its middle
          column, its name stretched into the gap, and a source reporting a live
          reading with no history behind it looked like a broken row rather than
          a new one. */}
      <div className="flex h-4 w-20 shrink-0 items-end gap-px">
        {padHistory(source.history).map((day: NightShiftDay | null, index: number) => (
          <Bar
            key={day ? day.day : `pad-${index}`}
            day={day ? day.day : null}
            ratio={day ? day.ratio : null}
            title={
              day === null ? 'kayıt yok' : day.ratio === null ? 'ölçüm yok' : formatIndex(day.ratio)
            }
          />
        ))}
      </div>

      {contributed ? (
        <span className="tabnum w-12 shrink-0 text-right font-mono text-xs text-fg">
          {formatIndex(source.ratio)}
        </span>
      ) : (
        // "taban yok" does not fit the column the ratios sit in and truncated
        // to "TABAN …", which reads as a value rather than as its absence. The
        // row's own title carries the figure and the reason.
        <span
          className="w-12 shrink-0 text-right text-2xs uppercase tracking-wide text-fg-subtle"
          title="Taban çizgisi bölmek için fazla küçük"
        >
          yok
        </span>
      )}
    </div>
  );
}

/**
 * How long the Gazette has gone without an extra edition.
 *
 * The rare event, stated whether or not it fired: a gauge that only mentions
 * the mükerrer on the days it happens gives a reader no way to tell "none
 * today" from "we are not looking".
 *
 * Drawn the way the Nothing Ever Happens strip is drawn on the other realm, and
 * for the same reason it exists there — the ordinary state of this reading is
 * having nothing to report, and a bar makes a long silence legible as a
 * measurement rather than as an empty row. Segments behind the marker carry
 * their colour at full strength and the one the marker stands in stops under
 * it, so the fill and the marker always say the same thing.
 */
function MukerrerStrip({
  days,
  today,
  last,
}: {
  days: number | null;
  today: boolean;
  last: string | null;
}) {
  const state = mukerrerState(days, today);
  const position = today ? 100 : mukerrerPosition(days);
  const fill = mukerrerFill(position);

  return (
    <div className="border-t border-line px-3 py-2">
      <div className="flex items-center gap-2">
        <Siren className={`h-3 w-3 shrink-0 ${today ? 'text-[var(--warn)]' : 'text-fg-subtle'}`} />
        <span className="label truncate">Mükerrer sessizliği</span>
        <span
          className="tabnum ml-auto shrink-0 font-mono text-xs"
          style={{ color: mukerrerColor(state) }}
        >
          {days === null ? UNKNOWN : `${days} gün`}
        </span>
      </div>

      <div className="relative mt-1.5 flex items-center gap-px">
        {MUKERRER_BANDS.map((band, i) => {
          const color = mukerrerColor(band.key);
          const lit = `color-mix(in srgb, ${color} 90%, transparent)`;
          const unlit = `color-mix(in srgb, ${color} 20%, transparent)`;
          return (
            <div
              key={band.key}
              title={band.label}
              className="h-1 flex-1 first:rounded-l-sm last:rounded-r-sm"
              style={{
                background:
                  i < fill.band
                    ? lit
                    : i > fill.band
                      ? unlit
                      : `linear-gradient(to right, ${lit} ${fill.within}%, ${unlit} ${fill.within}%)`,
              }}
            />
          );
        })}
        {position !== null && (
          <div
            className="pointer-events-none absolute top-1/2 h-2.5 w-0.5 rounded-full bg-fg"
            style={{
              left: `${position}%`,
              transform: `translate(${markerShift(position)}%, -50%)`,
            }}
          />
        )}
      </div>

      <p className="mt-1.5 truncate text-2xs text-fg-subtle">
        <span style={{ color: mukerrerColor(state) }}>{mukerrerCaption(days, today)}</span>
        {last &&
          ` · ${new Date(last).toLocaleDateString('tr-TR', { day: 'numeric', month: 'long', year: 'numeric' })}`}
      </p>
    </div>
  );
}
