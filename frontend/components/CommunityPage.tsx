'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, MessageSquare, Plus, RefreshCw, Users } from 'lucide-react';

import CommunitySidebar from '@/components/community/CommunitySidebar';
import FeedToolbar from '@/components/community/FeedToolbar';
import PostCard from '@/components/community/PostCard';
import CreatePostModal from '@/components/community/composer/CreatePostModal';
import EditPostModal from '@/components/community/composer/EditPostModal';
import { useAuth } from '@/contexts/AuthContext';
import {
  useCommunityFeed,
  useCreatePost,
  useDeletePost,
  useUpdatePost,
} from '@/hooks/useCommunity';
import { showToast } from '@/lib/queryClient';
import type { CommunityFeedSort, CommunityPost, CommunityPostType } from '@/lib/api';

export default function CommunityPage() {
  const { user } = useAuth();

  const [sort, setSort] = useState<CommunityFeedSort>('hot');
  const [type, setType] = useState<CommunityPostType | 'all'>('all');
  const [symbol, setSymbol] = useState<string | undefined>();
  const [scope, setScope] = useState<'all' | 'mine'>('all');
  const [composing, setComposing] = useState(false);
  const [editing, setEditing] = useState<CommunityPost | undefined>();

  // "My posts" is scoped by author, which the backend serves from a different
  // route — so the scope lives in the query key, not just in the UI.
  const authorId = scope === 'mine' && user ? user.id : undefined;

  const feed = useCommunityFeed({ sort, type, symbol, authorId });
  const createPost = useCreatePost();
  const updatePost = useUpdatePost();
  const deletePost = useDeletePost();

  const posts = feed.data?.pages.flatMap((page) => page.posts) ?? [];

  // Infinite scroll: a sentinel below the last card asks for the next page as
  // it comes into view.
  const sentinelRef = useRef<HTMLDivElement>(null);
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = feed;

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !hasNextPage) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: '400px' }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const handleSelectSymbol = useCallback((next: string) => {
    setSymbol(next);
    setScope('all');
  }, []);

  const handleSignedOutCompose = useCallback(() => {
    if (user) {
      setComposing(true);
      return;
    }
    showToast('Sign in to post');
  }, [user]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex shrink-0 flex-col justify-between gap-3 border-b border-line bg-surface px-4 py-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="flex items-center gap-2 text-md font-semibold text-fg">
            <Users className="h-3.5 w-3.5 text-fg-muted" />
            Community
          </h1>
          <p className="max-w-xl text-xs text-fg-subtle">
            Theses, charts and links from other traders — ranked by what the board finds useful.
          </p>
        </div>

        <div className="flex w-full items-center gap-2 sm:w-auto">
          <button
            type="button"
            onClick={() => void feed.refetch()}
            aria-label="Refresh the feed"
            className="rounded-md border border-line bg-surface p-1.5 text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${feed.isRefetching ? 'animate-spin' : ''}`} />
          </button>

          <button
            type="button"
            onClick={handleSignedOutCompose}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 sm:flex-none"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New post</span>
          </button>
        </div>
      </header>

      <div className="shrink-0 border-b border-line bg-bg px-4 py-2">
        <FeedToolbar
          sort={sort}
          onSortChange={setSort}
          type={type}
          onTypeChange={setType}
          symbol={symbol}
          onClearSymbol={() => setSymbol(undefined)}
          scope={scope}
          onScopeChange={setScope}
          canFilterMine={Boolean(user)}
        />
      </div>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
        <div className="flex w-full gap-4">
          <div className="min-w-0 flex-1">
            {feed.isLoading ? (
              <FeedGrid>
                <FeedSkeleton />
              </FeedGrid>
            ) : feed.isError ? (
              <EmptyState
                title="The board would not load"
                body="That is usually the backend being asleep. Try the refresh button."
              />
            ) : posts.length === 0 ? (
              <EmptyState
                title={scope === 'mine' ? 'You have not posted yet' : 'Nothing here yet'}
                body={
                  scope === 'mine'
                    ? 'Your posts will show up here once you write one.'
                    : symbol
                      ? `Nobody has posted about ${symbol} yet.`
                      : 'The board is quiet — start the conversation.'
                }
                action={
                  user ? (
                    <button
                      type="button"
                      onClick={() => setComposing(true)}
                      className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-base text-fg transition-colors hover:border-line-strong"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Write the first post
                    </button>
                  ) : undefined
                }
              />
            ) : (
              <>
                <FeedGrid>
                  {posts.map((post) => (
                    <PostCard
                      key={post.id}
                      post={post}
                      onEdit={setEditing}
                      onDelete={(target) => deletePost.mutate(target.id)}
                      isDeleting={deletePost.isPending}
                      onSelectSymbol={handleSelectSymbol}
                    />
                  ))}
                </FeedGrid>

                {/*
                 * Sentinel, spinner and the end note live outside the grid on
                 * purpose: `auto-rows-[26rem]` sizes every implicit row, so a
                 * full-width child in there would claim a card's worth of blank
                 * height and leave the feed scrolling into nothing.
                 */}
                <div ref={sentinelRef} className="h-px" aria-hidden="true" />

                {isFetchingNextPage && (
                  <div className="flex justify-center py-4 text-fg-subtle">
                    <Loader2 className="h-4 w-4 animate-spin" />
                  </div>
                )}

                {!hasNextPage && (
                  <p className="py-4 text-center text-sm text-fg-subtle">
                    That is the whole board.
                  </p>
                )}
              </>
            )}
          </div>

          <div className="hidden lg:block">
            <CommunitySidebar onSelectSymbol={handleSelectSymbol} />
          </div>
        </div>
      </div>

      <CreatePostModal
        isOpen={composing}
        onClose={() => setComposing(false)}
        isSubmitting={createPost.isPending}
        onSubmit={async (input) => {
          await createPost.mutateAsync(input);
          setComposing(false);
        }}
      />

      <EditPostModal
        post={editing}
        onClose={() => setEditing(undefined)}
        isSubmitting={updatePost.isPending}
        onSubmit={async (patch) => {
          if (!editing) return;
          await updatePost.mutateAsync({ postId: editing.id, patch });
          setEditing(undefined);
        }}
      />
    </div>
  );
}

/**
 * The card grid: three across once there is room for it, dropping to two and
 * then one as the viewport narrows. `items-start` is deliberately absent — the
 * cards stretch to a common row height so the grid reads as a grid rather than
 * as a ragged masonry.
 *
 * Only cards belong in here. `auto-rows` applies to every implicit row, so any
 * other child would be padded out to a full card height.
 */
function FeedGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:auto-rows-[26rem] md:grid-cols-2 xl:grid-cols-3">
      {children}
    </div>
  );
}

function FeedSkeleton() {
  // Six placeholders rather than three: at the widest breakpoint three would be
  // a single row and read as a much emptier board than the one that loads.
  return (
    <>
      {[0, 1, 2, 3, 4, 5].map((index) => (
        <div key={index} className="surface shimmer h-64 md:h-full" aria-hidden="true" />
      ))}
    </>
  );
}

function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="surface flex flex-col items-center px-6 py-16 text-center">
      <MessageSquare className="mb-3 h-6 w-6 text-fg-subtle" />
      <h2 className="mb-1.5 text-md font-semibold text-fg">{title}</h2>
      <p className="mb-5 max-w-sm text-base text-fg-muted">{body}</p>
      {action}
    </div>
  );
}
