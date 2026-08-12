'use client';

import { useState } from 'react';

import { AUDIT_PAGE_SIZE, useAdminAudit } from '@/hooks/useAdmin';
import type { AdminAuditEntry } from '@/lib/api';

const GRID = 'grid grid-cols-[150px_120px_1fr_170px] gap-2 px-4';

// Wording, not slugs. `user.plan` tells the reader nothing the sentence doesn't.
const ACTION_LABELS: Record<string, string> = {
  'user.ban': 'Suspended',
  'user.unban': 'Reinstated',
  'user.plan': 'Changed plan',
  'post.delete': 'Removed post',
  'comment.delete': 'Removed comment',
};

/**
 * The action trail.
 *
 * The reason it exists with one admin: plan and suspension changes overwrite in
 * place, and a post delete is a hard delete — so for both, this is the only
 * surviving record of the previous state.
 */
export default function AuditTab() {
  const [offset, setOffset] = useState(0);
  const { data, isLoading, isError } = useAdminAudit(offset);

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="surface overflow-hidden">
      <div className="flex items-center justify-between gap-4 border-b border-line px-4 py-2.5">
        <h2 className="text-md font-semibold text-fg">Audit log</h2>
        <span className="text-xs text-fg-subtle tabnum">{total} entries</span>
      </div>

      <div className={`${GRID} border-b border-line bg-surface-2 py-1.5`}>
        <div className="label">When</div>
        <div className="label">Action</div>
        <div className="label">Target</div>
        <div className="label">By</div>
      </div>

      {isLoading ? (
        <div className="divide-y divide-line" aria-hidden="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className={`${GRID} py-2.5`}>
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="px-4 py-10 text-center text-base text-fg-muted">
          The log would not load.
        </div>
      ) : entries.length === 0 ? (
        <div className="px-4 py-10 text-center text-base text-fg-muted">
          Nothing has been done yet.
        </div>
      ) : (
        <div className="divide-y divide-line">
          {entries.map((entry) => (
            <AuditRow key={entry.id} entry={entry} />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-4 border-t border-line px-4 py-2.5">
        <span className="text-xs text-fg-subtle tabnum">
          {total ? `${offset + 1}–${Math.min(offset + AUDIT_PAGE_SIZE, total)} of ${total}` : '0'}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(offset - AUDIT_PAGE_SIZE, 0))}
            className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + AUDIT_PAGE_SIZE >= total}
            onClick={() => setOffset(offset + AUDIT_PAGE_SIZE)}
            className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function AuditRow({ entry }: { entry: AdminAuditEntry }) {
  return (
    <div className={`${GRID} items-start py-2.5`}>
      <div className="font-mono text-xs text-fg-subtle tabnum">{formatWhen(entry.created_at)}</div>

      <div className="text-sm text-fg">{ACTION_LABELS[entry.action] ?? entry.action}</div>

      <div className="min-w-0">
        <div className="truncate text-sm text-fg-muted">{describeTarget(entry)}</div>
        {entry.reason && <div className="truncate text-xs text-fg-subtle">{entry.reason}</div>}
      </div>

      <div className="truncate font-mono text-xs text-fg-subtle">{entry.actor_email ?? '—'}</div>
    </div>
  );
}

/**
 * A readable sentence from the snapshot the service stored.
 *
 * Falls back to the id: for a hard-deleted post an old entry may predate the
 * snapshot, and an id is still better than an empty cell.
 */
function describeTarget(entry: AdminAuditEntry): string {
  const meta = entry.metadata ?? {};
  const text = (key: string): string | undefined => {
    const value = meta[key];
    return typeof value === 'string' && value ? value : undefined;
  };

  if (entry.target_type === 'user') {
    const email = text('email');
    if (entry.action === 'user.plan') {
      const from = text('from');
      const to = text('to');
      return `${email ?? entry.target_id} · ${from ?? '?'} → ${to ?? '?'}`;
    }
    return email ?? entry.target_id ?? '—';
  }

  return text('title') ?? text('content') ?? entry.target_id ?? '—';
}

function formatWhen(value: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toISOString().slice(0, 16).replace('T', ' ');
}
