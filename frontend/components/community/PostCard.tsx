'use client';

import { useCallback } from 'react';
import Link from 'next/link';
import { Link2, MessageSquare, Share2 } from 'lucide-react';

import { useAuth } from '@/contexts/AuthContext';
import { useAdminDeletePost, useIsAdmin } from '@/hooks/useAdmin';
import { nextVoteValue, useVoteOnPost } from '@/hooks/useCommunity';
import { showToast } from '@/lib/queryClient';
import type { CommunityPost } from '@/lib/api';

import PostBody from './PostBody';
import PostMenu from './PostMenu';
import VoteColumn from './VoteColumn';
import { NEUTRAL_TAG, Byline } from './PostMeta';

interface PostCardProps {
  post: CommunityPost;
  /** `detail` drops the permalink wrapper and stops capping the body. */
  variant?: 'feed' | 'detail';
  onEdit?: (post: CommunityPost) => void;
  onDelete?: (post: CommunityPost) => void;
  isDeleting?: boolean;
  /** Clicking the asset tag narrows the feed to that ticker. */
  onSelectSymbol?: (symbol: string) => void;
}

export default function PostCard({
  post,
  variant = 'feed',
  onEdit,
  onDelete,
  isDeleting,
  onSelectSymbol,
}: PostCardProps) {
  const { user } = useAuth();
  const vote = useVoteOnPost();
  const { data: adminSession } = useIsAdmin();
  const moderatorDelete = useAdminDeletePost();

  const isFeed = variant === 'feed';
  const isOwner = Boolean(user && post.author.id === user.id);
  // An admin gets the menu on anyone's post. The everyday moderation path is
  // here rather than in the admin panel, because this is where the post is
  // actually readable.
  const isModerator = Boolean(adminSession?.is_admin) && !isOwner;
  // The owner's menu still needs the caller's handlers; a moderator's does not,
  // because it goes straight to the admin endpoint.
  const canModerate = (isOwner && Boolean(onDelete)) || isModerator;
  const permalink = `/community/${post.id}`;

  const handleVote = useCallback(
    (direction: 1 | -1) => {
      if (!user) {
        showToast('Sign in to vote');
        return;
      }
      vote.mutate({ postId: post.id, value: nextVoteValue(post.my_vote, direction) });
    },
    [user, vote, post.id, post.my_vote]
  );

  const handleShare = useCallback(async () => {
    const url = `${window.location.origin}${permalink}`;
    try {
      await navigator.clipboard.writeText(url);
      showToast('Link copied');
    } catch {
      // Clipboard access is denied over plain http and in some embedded views.
      showToast(url);
    }
  }, [permalink]);

  return (
    // `h-full` only in the feed: the cards sit in a grid there and have to fill
    // the row height they were stretched to, or the footers of a row do not line
    // up. On the detail page the card is alone and sizes to its content.
    <article
      className={`surface flex transition-colors hover:border-line-strong ${isFeed ? 'h-full' : ''}`}
    >
      <VoteColumn score={post.score} myVote={post.my_vote} onVote={handleVote} disabled={!user} />

      <div className="flex min-w-0 flex-1 flex-col p-3">
        <Byline
          author={post.author}
          createdAt={post.created_at}
          isEdited={post.is_edited}
          showAvatar
          prefix={
            <>
              <span className={NEUTRAL_TAG}>{post.type}</span>
              {post.post_kind === 'link' && (
                <span className={NEUTRAL_TAG} title="Link post">
                  <Link2 className="inline h-2.5 w-2.5" />
                </span>
              )}
              {post.asset_symbol &&
                (onSelectSymbol ? (
                  <button
                    type="button"
                    onClick={() => onSelectSymbol(post.asset_symbol as string)}
                    className={`${NEUTRAL_TAG} font-mono transition-colors hover:border-line-strong hover:text-fg`}
                  >
                    {post.asset_symbol}
                  </button>
                ) : (
                  <span className={`${NEUTRAL_TAG} font-mono`}>{post.asset_symbol}</span>
                ))}
            </>
          }
        />

        {post.title &&
          (isFeed ? (
            <Link
              href={permalink}
              className="mt-1.5 block text-md font-semibold leading-tight text-fg transition-colors hover:text-accent"
            >
              {post.title}
            </Link>
          ) : (
            <h1 className="mt-1.5 text-lg font-semibold leading-tight text-fg">{post.title}</h1>
          ))}

        {/*
         * In the feed the body takes whatever height the fixed-height card has
         * left and clips the rest, with a fade marking the cut. Every card is
         * the same size regardless of how long the post is, and a long post
         * shows a readable opening rather than being sized around.
         */}
        <div className={isFeed ? 'relative mb-3 mt-2 min-h-0 flex-1 overflow-hidden' : 'mb-3 mt-2'}>
          <PostBody post={post} compact={isFeed} />
          {isFeed && (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-surface to-transparent"
            />
          )}
        </div>

        {/* `mt-auto` pins the action row to the bottom of a stretched card. */}
        <div className="mt-auto flex items-center gap-4 border-t border-line pt-2.5">
          {isFeed ? (
            <Link
              href={permalink}
              className="flex items-center gap-1.5 font-mono text-sm text-fg-subtle tabnum transition-colors hover:text-fg"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span>{post.comments_count}</span>
              <span className="font-sans">{post.comments_count === 1 ? 'reply' : 'replies'}</span>
            </Link>
          ) : (
            <span className="flex items-center gap-1.5 font-mono text-sm text-fg-subtle tabnum">
              <MessageSquare className="h-3.5 w-3.5" />
              <span>{post.comments_count}</span>
              <span className="font-sans">{post.comments_count === 1 ? 'reply' : 'replies'}</span>
            </span>
          )}

          <button
            type="button"
            onClick={handleShare}
            className="flex items-center gap-1.5 text-sm text-fg-subtle transition-colors hover:text-fg"
          >
            <Share2 className="h-3.5 w-3.5" />
            <span>Share</span>
          </button>

          {canModerate && (
            <div className="ml-auto">
              <PostMenu
                // A moderator gets no Edit: rewriting someone else's post is a
                // different act from removing it, and not one an admin should
                // be able to do silently.
                onEdit={isOwner && onEdit ? () => onEdit(post) : undefined}
                onDelete={
                  isModerator
                    ? () => moderatorDelete.mutate({ postId: post.id })
                    : onDelete
                      ? () => onDelete(post)
                      : () => undefined
                }
                isDeleting={isDeleting || moderatorDelete.isPending}
                isModerator={isModerator}
              />
            </div>
          )}
        </div>
      </div>
    </article>
  );
}
