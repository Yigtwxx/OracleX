import type { LiveEvent, LiveEventKind } from '@/lib/api';

/**
 * Formatting for the Live tab.
 *
 * One rule runs through all of it: the server sends UTC instants and nothing
 * else, and every human-readable time is produced here, in the browser, from
 * the reader's own clock. A time formatted on the server would be correct only
 * for whoever deployed it.
 */

/** Local wall-clock time, e.g. "18:30". */
export function formatLocalTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/**
 * The same instant in UTC, e.g. "15:30Z".
 *
 * Shown alongside the local time because this tab is read against sources that
 * publish in UTC — a headline saying "the decision lands at 18:00 GMT" has to
 * be checkable against the row without arithmetic.
 */
export function formatUtcTime(iso: string): string {
  const date = new Date(iso);
  const hours = String(date.getUTCHours()).padStart(2, '0');
  const minutes = String(date.getUTCMinutes()).padStart(2, '0');
  return `${hours}:${minutes}Z`;
}

/** The reader's timezone as a short label, e.g. "GMT+3" — shown once, in the header. */
export function localZoneLabel(): string {
  const parts = new Intl.DateTimeFormat([], { timeZoneName: 'shortOffset' }).formatToParts(
    new Date()
  );
  return parts.find((part) => part.type === 'timeZoneName')?.value ?? 'local';
}

/**
 * How far away an event is, as a compact string: "4h 12m", "58m", "now".
 *
 * Returns null past the hour mark in either direction — a countdown to
 * something three days out is noise, and the row's date already says it.
 */
export function formatDistance(iso: string, now: number): string | null {
  const deltaMs = new Date(iso).getTime() - now;
  const absMinutes = Math.floor(Math.abs(deltaMs) / 60_000);
  if (absMinutes < 1) return 'now';
  if (absMinutes >= 60 * 24) return null;

  const hours = Math.floor(absMinutes / 60);
  const minutes = absMinutes % 60;
  // "1h" rather than "1h 0m" on the hour: the trailing zero reads as precision
  // this figure does not have, and the column is narrow.
  const magnitude =
    hours === 0 ? `${minutes}m` : minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`;
  return deltaMs > 0 ? `in ${magnitude}` : `${magnitude} ago`;
}

/** Minutes since a live event started, for the elapsed clock on the LIVE strip. */
export function formatElapsed(iso: string, now: number): string {
  const elapsedSeconds = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Which day group a row belongs to.
 *
 * Compared on local calendar days rather than on elapsed hours, so an event
 * eight hours away lands under "Tomorrow" when that is what the clock on the
 * wall says.
 */
export function dayGroup(iso: string, now: number): 'today' | 'tomorrow' | 'later' {
  const event = new Date(iso);
  const reference = new Date(now);
  const startOfDay = (date: Date) =>
    new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const dayDelta = Math.round((startOfDay(event) - startOfDay(reference)) / 86_400_000);
  if (dayDelta <= 0) return 'today';
  if (dayDelta === 1) return 'tomorrow';
  return 'later';
}

/** Weekday and date for the "later" group's sub-headings, e.g. "Thu 14 Aug". */
export function formatDayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

export const KIND_LABELS: Record<LiveEventKind, string> = {
  central_bank: 'Central banks',
  political: 'Political',
  macro_data: 'Data',
  corporate: 'Earnings',
};

/**
 * The impact dot's colour.
 *
 * Only high impact gets a signal colour. A three-colour ramp would make the
 * whole column shout, and the point of the dot is that a handful of rows in a
 * long list are worth stopping on.
 */
export function impactDotClass(impact: LiveEvent['impact']): string {
  if (impact === 'high') return 'bg-down';
  if (impact === 'medium') return 'bg-warn';
  return 'bg-fg-subtle';
}

/** Sort helper: events the reader has not seen yet come first, soonest first. */
export function byStartAscending(a: LiveEvent, b: LiveEvent): number {
  return a.starts_at.localeCompare(b.starts_at);
}
