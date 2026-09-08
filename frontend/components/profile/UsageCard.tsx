'use client';

import { Activity, AlertTriangle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { getAiUsage, type AiUsage, type UsageWindow } from '@/lib/api';
import {
  breakdownRows,
  emptyMessage,
  featureLabel,
  formatDuration,
  formatTokens,
  tokenCoverage,
  WINDOW_LABELS,
  WINDOWS,
} from '@/lib/usage';

import ProfileCard from './ProfileCard';

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-md border border-line px-3 py-2.5">
      <p className="label mb-1">{label}</p>
      <p className="tabnum text-md font-semibold text-fg">{value}</p>
      {note && <p className="mt-0.5 text-xs text-fg-subtle">{note}</p>}
    </div>
  );
}

function Breakdown({
  title,
  group,
  totalTokens,
  labeller = (k: string) => k,
}: {
  title: string;
  group: Record<string, import('@/lib/api').UsageTotals>;
  totalTokens: number;
  labeller?: (key: string) => string;
}) {
  const rows = breakdownRows(group, totalTokens);
  if (rows.length === 0) return null;

  return (
    <div>
      <p className="label mb-1.5">{title}</p>
      <div className="space-y-1.5">
        {rows.map(({ key, totals, share }) => (
          <div key={key} className="flex items-center gap-3">
            <span className="w-44 shrink-0 truncate text-base text-fg" title={labeller(key)}>
              {labeller(key)}
            </span>
            {/* A bar rather than a chart: this is a proportion of one total, and
                a reader compares the rows to each other, not to an axis. */}
            <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-2">
              <span
                className="block h-full rounded-full bg-accent"
                style={{ width: `${Math.max(share * 100, share > 0 ? 2 : 0)}%` }}
              />
            </span>
            <span className="tabnum w-24 shrink-0 text-right text-base text-fg-muted">
              {formatTokens(totals.total_tokens)}
            </span>
            <span className="tabnum w-20 shrink-0 text-right text-xs text-fg-subtle">
              {totals.requests} {totals.requests === 1 ? 'call' : 'calls'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * What the terminal's AI has actually cost this reader.
 *
 * Nothing measured this before: the "AI queries today" meter on the plan card
 * counts a route no client has ever called. These figures come from one row per
 * model call, written as the calls are made.
 */
export default function UsageCard() {
  const [window, setWindow] = useState<UsageWindow>('30d');
  const [usage, setUsage] = useState<AiUsage | undefined>(undefined);
  const [error, setError] = useState('');

  const load = useCallback(async (next: UsageWindow) => {
    try {
      setError('');
      setUsage(await getAiUsage(next));
    } catch {
      setError('Could not load usage.');
    }
  }, []);

  useEffect(() => {
    void load(window);
  }, [load, window]);

  if (!usage && !error) {
    return <div className="surface shimmer h-96" />;
  }

  const totals = usage?.totals;
  const coverage = totals ? tokenCoverage(totals) : null;
  const empty = usage ? emptyMessage(usage) : null;
  const ownCalls = usage?.by_key_owner.user?.requests ?? 0;

  return (
    <ProfileCard
      title="AI Usage"
      icon={Activity}
      action={
        <div className="flex gap-0.5" role="group" aria-label="Window">
          {WINDOWS.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={window === key}
              onClick={() => setWindow(key)}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                window === key ? 'bg-surface-2 text-fg' : 'text-fg-subtle hover:text-fg'
              }`}
            >
              {WINDOW_LABELS[key]}
            </button>
          ))}
        </div>
      }
    >
      <div className="space-y-5">
        {error && (
          <p role="alert" className="text-base text-down">
            {error}
          </p>
        )}

        {usage && !usage.available && (
          <div className="flex items-start gap-2 rounded-md border border-warn bg-warn-bg p-3 text-base text-warn">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>{empty}</span>
          </div>
        )}

        {usage && usage.available && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Tile
                label="Requests"
                value={usage.totals.requests.toLocaleString('en-US')}
                note={usage.totals.failed > 0 ? `${usage.totals.failed} failed` : undefined}
              />
              <Tile label="Total tokens" value={formatTokens(usage.totals.total_tokens)} />
              <Tile label="Sent" value={formatTokens(usage.totals.prompt_tokens)} note="prompt" />
              <Tile
                label="Received"
                value={formatTokens(usage.totals.completion_tokens)}
                note="completion"
              />
            </div>

            {coverage && !coverage.complete && (
              <p className="text-xs text-fg-subtle">{coverage.note}</p>
            )}

            {empty ? (
              <p className="text-base text-fg-muted">{empty}</p>
            ) : (
              <>
                <Breakdown
                  title="By surface"
                  group={usage.by_feature}
                  totalTokens={usage.totals.total_tokens}
                  labeller={featureLabel}
                />
                <Breakdown
                  title="By provider"
                  group={usage.by_provider}
                  totalTokens={usage.totals.total_tokens}
                />

                {/* The question an operator actually has: how much of this did I
                    pay for. A reader on their own key costs the install nothing. */}
                <p className="text-xs text-fg-subtle">
                  {ownCalls > 0
                    ? `${ownCalls} of ${usage.totals.requests} calls ran on your own API key; the rest used this install's provider.`
                    : "Every call used this install's provider. Save your own key under AI Provider to run them on yours instead."}
                </p>

                {usage.recent.length > 0 && (
                  <div>
                    <p className="label mb-1.5">Recent calls</p>
                    <div className="custom-scrollbar max-h-64 overflow-y-auto">
                      <table className="w-full text-base">
                        <tbody>
                          {usage.recent.map((call, i) => (
                            <tr key={`${call.created_at}-${i}`} className="border-b border-line">
                              <td className="py-1.5 pr-3 text-fg-muted">
                                {featureLabel(call.feature)}
                              </td>
                              <td className="py-1.5 pr-3 font-mono text-xs text-fg-subtle">
                                {call.provider}
                                {call.model ? ` · ${call.model}` : ''}
                              </td>
                              <td className="tabnum py-1.5 pr-3 text-right text-fg">
                                {call.total_tokens === null ? '—' : formatTokens(call.total_tokens)}
                              </td>
                              <td className="tabnum py-1.5 pr-3 text-right text-xs text-fg-subtle">
                                {formatDuration(call.duration_ms)}
                              </td>
                              <td className="py-1.5 text-right text-xs">
                                {call.ok ? (
                                  <span className="text-fg-subtle">
                                    {call.key_owner === 'user' ? 'your key' : 'server'}
                                  </span>
                                ) : (
                                  <span className="text-down">failed</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </ProfileCard>
  );
}
