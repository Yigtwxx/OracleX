'use client';

import Link from 'next/link';
import { ArrowBigUp, FileText, MessageSquare, Trophy } from 'lucide-react';

import PostCard from '@/components/community/PostCard';
import StatCard from '@/components/social/StatCard';
import { useCommunityFeed } from '@/hooks/useCommunity';
import { useCommunityActivity } from '@/hooks/useSocial';

/**
 * How the member's own writing has actually done.
 *
 * Every number is computed on read by `community_user_activity()`. Nothing here
 * is stored as a counter, so deleting a post or retracting a vote is reflected
 * the next time this loads rather than drifting away from the truth.
 */
export default function ActivityTab({ userId }: { userId: string }) {
  const { data: activity, isLoading } = useCommunityActivity();
  const feed = useCommunityFeed({ sort: 'new', type: 'all', authorId: userId });

  const posts = feed.data?.pages.flatMap((page) => page.posts) ?? [];

  return (
    <div className="custom-scrollbar h-full overflow-y-auto p-4">
      <div className="mx-auto w-full max-w-4xl space-y-4">
        {isLoading || !activity ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((card) => (
              <div key={card} className="surface shimmer h-24" />
            ))}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatCard label="Karma" value={activity.total_karma} icon={ArrowBigUp} />
              <StatCard label="Posts" value={activity.post_count} icon={FileText} />
              <StatCard label="Comments" value={activity.comment_count} icon={MessageSquare} />
              <StatCard
                label="Post karma"
                value={activity.post_karma}
                icon={Trophy}
                hint={`${activity.comment_karma.toLocaleString()} from comments`}
              />
            </div>

            {activity.best_post && (
              <Link
                href={`/community/${activity.best_post.id}`}
                className="surface flex items-center gap-3 p-4 transition-colors hover:border-line-strong"
              >
                <Trophy className="h-4 w-4 shrink-0 text-fg-muted" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-fg-subtle">Your best post</p>
                  <p className="truncate text-base text-fg">
                    {activity.best_post.title || 'Untitled'}
                  </p>
                </div>
                <span className="shrink-0 text-md font-semibold tabular-nums text-fg">
                  {activity.best_post.score > 0 ? '+' : ''}
                  {activity.best_post.score}
                </span>
              </Link>
            )}
          </>
        )}

        <section>
          <h2 className="mb-2 text-md font-semibold text-fg">Your posts</h2>

          {feed.isLoading ? (
            <div className="space-y-2">
              <div className="surface shimmer h-24" />
              <div className="surface shimmer h-24" />
            </div>
          ) : posts.length === 0 ? (
            <div className="surface p-6 text-center">
              <p className="text-base text-fg-muted">You have not posted yet.</p>
              <Link
                href="/community"
                className="mt-1 inline-block text-sm text-accent hover:underline"
              >
                Go to the Community board
              </Link>
            </div>
          ) : (
            <div className="space-y-2">
              {posts.map((post) => (
                <PostCard key={post.id} post={post} />
              ))}

              {feed.hasNextPage && (
                <button
                  type="button"
                  onClick={() => void feed.fetchNextPage()}
                  disabled={feed.isFetchingNextPage}
                  className="w-full rounded-md border border-line py-2 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
                >
                  {feed.isFetchingNextPage ? 'Loading…' : 'Show more'}
                </button>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
