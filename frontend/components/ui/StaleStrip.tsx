import { AlertTriangle } from 'lucide-react';

interface StaleStripProps {
  /** The API's own flag: this board is a replay of the last good fetch. */
  stale?: boolean;
  /** A refresh failed while data was already on screen. */
  refreshFailed?: boolean;
  /** When the data on screen was produced, ISO 8601. */
  asOf?: string | null;
  /**
   * Age in seconds, for the boards whose API reports it that way instead.
   *
   * Two inputs for one fact because the two surfaces genuinely differ: the BIST
   * payloads carry an `as_of` timestamp and the heatmap carries `age_seconds`.
   * Converting either at the call site would put the same three-line branch in
   * every consumer.
   */
  ageSeconds?: number;
  onRetry?: () => void;
  /** Turkish by default; the global realm passes English. */
  labels?: StaleStripLabels;
}

export interface StaleStripLabels {
  stale: string;
  failed: string;
  retry: string;
  /** Shown when neither an `as_of` nor an age is available. */
  unknownAge: string;
  /** Joined between the message and the age, e.g. "· 4m ago". */
  suffix: string;
}

const DEFAULT_LABELS: StaleStripLabels = {
  stale: 'Gösterilen veri',
  failed: 'Yenilenemedi — gösterilen veri',
  retry: 'Tekrar dene',
  unknownAge: 'bir süre',
  suffix: 'önce',
};

export const ENGLISH_LABELS: StaleStripLabels = {
  stale: 'Showing data from',
  failed: "Couldn't refresh — showing data from",
  retry: 'Retry',
  unknownAge: 'a moment',
  suffix: 'ago',
};

function relativeAge(
  asOf: string | null | undefined,
  ageSeconds: number | undefined,
  unknown: string
): string {
  const seconds =
    ageSeconds !== undefined
      ? ageSeconds
      : asOf
        ? (Date.now() - new Date(asOf).getTime()) / 1000
        : NaN;
  if (!Number.isFinite(seconds)) return unknown;
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

/**
 * A badge, never a takeover.
 *
 * Staleness comes from the API payload rather than from react-query: the server
 * knows it is replaying a cached snapshot because an upstream is down, and
 * react-query only knows whether *its own* request succeeded. The two are
 * different facts and a reader needs the first one.
 *
 * `refreshFailed` covers the other half — data on screen, refresh failed. The
 * rule the boards follow is that this renders as a strip above a populated
 * view, and only a cold failure (`isError && !data`) gets the whole pane.
 */
export default function StaleStrip({
  stale,
  refreshFailed,
  asOf,
  ageSeconds,
  onRetry,
  labels = DEFAULT_LABELS,
}: StaleStripProps) {
  if (!stale && !refreshFailed) return null;

  return (
    <div
      role="status"
      className="flex shrink-0 items-center gap-2 rounded-md border border-line bg-warn-bg px-3 py-1.5 text-xs text-fg"
    >
      <AlertTriangle className="h-3 w-3 shrink-0 text-warn" aria-hidden="true" />
      <span>
        {refreshFailed ? labels.failed : labels.stale}{' '}
        {relativeAge(asOf, ageSeconds, labels.unknownAge)} {labels.suffix}
      </span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="underline underline-offset-2 hover:text-fg"
        >
          {labels.retry}
        </button>
      )}
    </div>
  );
}
