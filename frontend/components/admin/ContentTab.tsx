'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ExternalLink, Search, Trash2 } from 'lucide-react';

import { POSTS_PAGE_SIZE, useAdminDeletePost, useAdminPosts } from '@/hooks/useAdmin';
import type { AdminPostSummary } from '@/lib/api';

const GRID = 'grid grid-cols-[1fr_170px_70px_110px_96px] gap-2 px-4';

/**
 * The content browser.
 *
 * The everyday way to remove a post is the menu on the card itself, where the
 * whole post is visible. This tab is the fallback for the times you have a
 * report and a phrase rather than a link.
 */
export default function ContentTab() {
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [confirming, setConfirming] = useState<string | undefined>();

  const { data, isLoading, isError } = useAdminPosts({
    search: search.trim() || undefined,
    limit: POSTS_PAGE_SIZE,
    offset,
  });
  const remove = useAdminDeletePost();

  const posts = data?.posts ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="surface overflow-hidden">
      <div className="flex flex-col justify-between gap-3 border-b border-line px-4 py-2.5 sm:flex-row sm:items-center">
        <h2 className="text-md font-semibold text-fg">Posts</h2>

        <div className="flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1 transition-colors focus-within:border-accent">
          <Search className="h-3 w-3 text-fg-subtle" />
          <input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setOffset(0);
            }}
            placeholder="Title or body"
            aria-label="Search posts"
            className="w-44 bg-transparent text-base text-fg outline-none placeholder:text-fg-subtle"
          />
        </div>
      </div>

      <div className={`${GRID} border-b border-line bg-surface-2 py-1.5`}>
        <div className="label">Post</div>
        <div className="label">Author</div>
        <div className="label text-right">Score</div>
        <div className="label">Posted</div>
        <div className="label text-right">Actions</div>
      </div>

      {isLoading ? (
        <div className="divide-y divide-line" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className={`${GRID} py-2.5`}>
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
              <div className="h-4 rounded bg-surface-2 shimmer" />
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="px-4 py-10 text-center text-base text-fg-muted">
          The board would not load.
        </div>
      ) : posts.length === 0 ? (
        <div className="px-4 py-10 text-center text-base text-fg-muted">Nothing matches that.</div>
      ) : (
        <div className="divide-y divide-line">
          {posts.map((post) => (
            <PostRow
              key={post.id}
              post={post}
              confirming={confirming === post.id}
              isBusy={remove.isPending}
              onAskConfirm={() => setConfirming(post.id)}
              onCancel={() => setConfirming(undefined)}
              onConfirm={() => {
                remove.mutate({ postId: post.id, reason: 'Removed from the admin panel' });
                setConfirming(undefined);
              }}
            />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-4 border-t border-line px-4 py-2.5">
        <span className="text-xs text-fg-subtle tabnum">
          {total ? `${offset + 1}–${Math.min(offset + POSTS_PAGE_SIZE, total)} of ${total}` : '0'}
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(offset - POSTS_PAGE_SIZE, 0))}
            className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + POSTS_PAGE_SIZE >= total}
            onClick={() => setOffset(offset + POSTS_PAGE_SIZE)}
            className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

interface PostRowProps {
  post: AdminPostSummary;
  confirming: boolean;
  isBusy: boolean;
  onAskConfirm: () => void;
  onCancel: () => void;
  onConfirm: () => void;
}

function PostRow({ post, confirming, isBusy, onAskConfirm, onCancel, onConfirm }: PostRowProps) {
  return (
    <div className={`${GRID} items-center py-2.5`}>
      <div className="min-w-0">
        <Link
          href={`/community/${post.id}`}
          className="flex items-center gap-1.5 truncate text-base text-fg transition-colors hover:text-accent"
        >
          <span className="truncate">{post.title || post.content_preview.slice(0, 60)}</span>
          <ExternalLink className="h-3 w-3 shrink-0 text-fg-subtle" />
        </Link>
        <div className="truncate text-xs text-fg-subtle">{post.content_preview}</div>
      </div>

      <div className="min-w-0">
        <div className="truncate text-sm text-fg-muted">{post.author_name || 'Unknown'}</div>
        <div className="truncate font-mono text-xs text-fg-subtle">{post.author_email ?? '—'}</div>
      </div>

      <div className="text-right font-mono text-sm text-fg-muted tabnum">{post.score}</div>

      <div className="font-mono text-xs text-fg-subtle tabnum">
        {post.created_at ? post.created_at.slice(0, 10) : '—'}
      </div>

      <div className="flex justify-end">
        {/* Two clicks, because a post delete is a hard delete: its comments and
            votes cascade away with it and there is no undo. */}
        {confirming ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onConfirm}
              disabled={isBusy}
              className="rounded-md border border-down px-2 py-1 text-sm text-down transition-opacity hover:opacity-80 disabled:opacity-50"
            >
              Confirm
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:text-fg"
            >
              No
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={onAskConfirm}
            title="Remove post"
            aria-label="Remove post"
            className="rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:border-down hover:text-down"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}
