'use client';

import Link from 'next/link';
import { Eye, Pencil } from 'lucide-react';

import PublicProfilePage from '@/components/profile/PublicProfilePage';

/**
 * Your own public profile, rendered by the same component strangers get.
 *
 * Deliberately not a separate mock-up of it. A preview built from its own
 * markup drifts from the real page the first time either changes, and then it
 * is worse than no preview at all — it shows something that is not true.
 */
export default function PreviewTab({ userId }: { userId: string }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-surface px-4 py-2">
        <Eye className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
        <p className="min-w-0 flex-1 text-sm text-fg-muted">
          This is exactly what another member sees at{' '}
          <span className="font-mono text-fg-subtle">/u/{userId}</span>
        </p>
        <Link
          href="/profile"
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          <Pencil className="h-3 w-3" />
          Edit
        </Link>
      </div>

      <div className="min-h-0 flex-1">
        <PublicProfilePage userId={userId} />
      </div>
    </div>
  );
}
