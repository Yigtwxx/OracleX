import type { OverallStatus, SourceState } from '@/hooks/useSystemHealth';

/** How the badge renders one overall status. */
export interface BadgeAppearance {
  label: string;
  /** A `var(--…)` colour reference, so the badge follows the theme tokens. */
  color: string;
  /** Whether the dot pulses. Only a healthy feed animates — a red pulse reads
      as an alarm demanding action, and a degraded provider rarely is one. */
  pulse: boolean;
}

const BADGE: Record<OverallStatus, BadgeAppearance> = {
  live: { label: 'LIVE', color: 'var(--up)', pulse: true },
  degraded: { label: 'DEGRADED', color: 'var(--warn)', pulse: false },
  offline: { label: 'OFFLINE', color: 'var(--down)', pulse: false },
  starting: { label: 'STARTING', color: 'var(--fg-subtle)', pulse: false },
};

export function badgeAppearance(status: OverallStatus): BadgeAppearance {
  return BADGE[status] ?? BADGE.starting;
}

/** Dot colour for one category row. */
export function stateColor(state: SourceState): string {
  switch (state) {
    case 'ok':
      return 'var(--up)';
    case 'degraded':
      return 'var(--warn)';
    // Neutral, like idle: nothing is wrong with a source that was last used an
    // hour ago, so it must not borrow the colour of one that is failing.
    case 'stale':
      return 'var(--fg-subtle)';
    case 'down':
      return 'var(--down)';
    default:
      return 'var(--fg-subtle)';
  }
}

/**
 * How long ago a category last worked, in the shortest honest unit.
 *
 * Returns null when it has never worked — the caller renders that as "no data"
 * rather than as an age, because "0s ago" would claim a success that never
 * happened.
 */
export function formatAge(lastOkAt: number | null, nowMs: number = Date.now()): string | null {
  if (lastOkAt === null) return null;
  const seconds = Math.max(0, Math.round(nowMs / 1000 - lastOkAt));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * The right-hand half of a row: what happened, and how long it took.
 *
 * A fault replaces the latency rather than joining it — the reason a call
 * failed is what the reader needs, and the time it took to fail is not.
 */
export function formatDetail(
  state: SourceState,
  lastOkAt: number | null,
  latencyMs: number | null,
  detail: string | null,
  nowMs: number = Date.now()
): string {
  if (state === 'idle') return 'no data yet';

  const age = formatAge(lastOkAt, nowMs);
  // Says why the row is quiet rather than leaving a bare age next to a grey
  // dot, which reads as "last seen" — as if contact had been lost.
  if (state === 'stale') return age ? `used ${age}` : 'no data yet';
  const parts: string[] = [];
  if (age) parts.push(age);
  if (state === 'ok') {
    if (latencyMs !== null) parts.push(`${latencyMs}ms`);
  } else if (detail) {
    parts.push(detail);
  }
  return parts.join(' · ');
}
