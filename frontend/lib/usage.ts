/**
 * Presentation rules for AI usage.
 *
 * Pure, and in `lib/` rather than in the component, because this is where the
 * judgement calls live: what a token total rounds to, what an empty history
 * should say, and — the one that matters — how to show a total that is known to
 * undercount without either hiding it or making the whole figure look wrong.
 */

import type { AiUsage, UsageTotals, UsageWindow } from './api';

export const WINDOW_LABELS: Record<UsageWindow, string> = {
  today: 'Last 24h',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
  all: 'All time',
};

export const WINDOWS: UsageWindow[] = ['today', '7d', '30d', 'all'];

/** How the terminal names each surface. The API's keys are its own vocabulary. */
const FEATURE_LABELS: Record<string, string> = {
  chat: 'Oracle Chat',
  news: 'News analysis',
  reports: 'Reports & bet analysis',
  notes: 'AI notes',
  background: 'Scheduled jobs',
  other: 'Other requests',
  unknown: 'Unattributed',
};

export function featureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? key;
}

/**
 * Tokens, short enough to sit in a tile.
 *
 * Thousands separators rather than "1.2M": a token count is a number people
 * compare against a provider's quota, and a rounded one cannot be compared.
 * Only past a million — where the exact digits stop being actionable — does it
 * abbreviate.
 */
export function formatTokens(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '0';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  return value.toLocaleString('en-US');
}

export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Whether the totals are known to be incomplete, and by how much.
 *
 * A provider that reports no usage is recorded with null tokens rather than
 * zero, so a total can be right about the requests and short on the tokens.
 * Saying which beats a figure that silently understates.
 */
export function tokenCoverage(totals: UsageTotals): {
  complete: boolean;
  missing: number;
  note: string;
} {
  const missing = totals.requests_without_token_data;
  if (missing <= 0) {
    return { complete: true, missing: 0, note: '' };
  }
  const calls = missing === 1 ? 'call' : 'calls';
  return {
    complete: false,
    missing,
    note: `${missing} ${calls} reported no token counts, so the totals below are a floor.`,
  };
}

/** Rows for the breakdown table, largest first, with a share of the total. */
export function breakdownRows(
  group: Record<string, UsageTotals>,
  totalTokens: number
): { key: string; totals: UsageTotals; share: number }[] {
  return Object.entries(group)
    .map(([key, totals]) => ({
      key,
      totals,
      // Falls back to request share when nothing reported tokens, so a
      // provider that hides its usage still gets a proportional bar rather
      // than an empty one.
      share: totalTokens > 0 ? totals.total_tokens / totalTokens : 0,
    }))
    .sort(
      (a, b) =>
        b.totals.total_tokens - a.totals.total_tokens || b.totals.requests - a.totals.requests
    );
}

/**
 * What the panel says when there is nothing to show.
 *
 * The distinction is worth the branch: an unreadable table is a fault, an empty
 * one after a fresh deploy is not, and telling a reader "no usage" when the
 * query failed would be a lie in the direction that hides a problem.
 */
export function emptyMessage(usage: AiUsage): string | null {
  if (!usage.available) {
    return 'Usage could not be read right now. The figures below are not a measurement.';
  }
  if (usage.totals.requests === 0) {
    return 'No AI calls recorded in this window yet.';
  }
  return null;
}

/** Share of spend the reader's own key paid for, 0–1. */
export function ownKeyShare(usage: AiUsage): number {
  const own = usage.by_key_owner.user?.requests ?? 0;
  const total = usage.totals.requests;
  return total > 0 ? own / total : 0;
}
