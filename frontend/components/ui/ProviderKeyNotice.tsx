'use client';

import { KeyRound } from 'lucide-react';
import Link from 'next/link';

import { isActionable, type ProviderNotice } from '@/lib/provider-keys';

/**
 * "A key would show you more here."
 *
 * A strip above the board, not a panel replacing it. These upstreams are
 * optional by design and every one of these pages renders real data without
 * them — nominal returns, thirty days of open interest — so hiding that behind a
 * setup screen would trade working content for a form. The strip says what is
 * missing, what a key adds, and where to put one.
 *
 * Tone is `warn` rather than `down`: nothing here has failed.
 */
export default function ProviderKeyNotice({
  notice,
  variant = 'strip',
}: {
  notice: ProviderNotice | undefined;
  /**
   * `chip` for toolbars, where a full-width strip would push a fixed-height
   * chart out of its panel. Same copy, carried in the tooltip instead.
   */
  variant?: 'strip' | 'chip';
}) {
  if (!notice) return null;

  if (variant === 'chip') {
    const title = `${notice.title} — ${notice.body}`;
    return isActionable(notice) ? (
      <Link
        href={notice.href}
        title={title}
        className="flex items-center gap-1 rounded bg-warn-bg px-1.5 py-0.5 text-2xs text-warn transition-opacity hover:opacity-80"
      >
        <KeyRound className="h-2.5 w-2.5" aria-hidden />
        {notice.action}
      </Link>
    ) : (
      <span className="rounded bg-surface-2 px-1.5 py-0.5 text-2xs text-fg-subtle" title={title}>
        {notice.title}
      </span>
    );
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md border border-warn/40 bg-warn-bg px-3 py-2"
    >
      <KeyRound className="h-4 w-4 shrink-0 text-warn" aria-hidden />
      <p className="min-w-0 flex-1 text-base text-warn">
        <span className="font-semibold">{notice.title}</span>
        <span className="text-fg-muted"> — {notice.body}</span>
      </p>
      {isActionable(notice) && (
        <Link
          href={notice.href}
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          {notice.action}
        </Link>
      )}
    </div>
  );
}
