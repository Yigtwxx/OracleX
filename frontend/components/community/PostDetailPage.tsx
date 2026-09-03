'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowLeft, MessageSquare } from 'lucide-react';

import EditPostModal from '@/components/community/composer/EditPostModal';
import { useAuth } from '@/contexts/AuthContext';
import {
  useCommunityComments,
  useCommunityPost,
  useCreateComment,
  useDeletePost,
  useUpdatePost,
} from '@/hooks/useCommunity';
import type { CommunityPost } from '@/lib/api';

import CommentComposer from './CommentComposer';
import CommentThread from './CommentThread';
import PostCard from './PostCard';

/**
 * A post on its own route.
 *
 * Being permalinkable is what makes the Share button mean something, and it is
 * where the full thread lives — the feed only shows a reply count.
 */
export default function PostDetailPage({ postId }: { postId: string }) {
  const router = useRouter();
  const { user } = useAuth();
  const [editing, setEditing] = useState<CommunityPost | undefined>();

  const post = useCommunityPost(postId);
  const thread = useCommunityComments(postId);
  const createComment = useCreateComment(postId);
  const updatePost = useUpdatePost();
  const deletePost = useDeletePost();

  // Arriving from a permalink, the heading is what the reader came for.
  const headingRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (post.data) headingRef.current?.focus();
  }, [post.data]);

  const handleReply = useCallback(
    (parentId: string, content: string) => createComment.mutateAsync({ content, parentId }),
    [createComment]
  );

  const handleDelete = useCallback(
    async (target: CommunityPost) => {
      await deletePost.mutateAsync(target.id);
      router.push('/community');
    },
    [deletePost, router]
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-surface px-4 py-3">
        <Link
          href="/community"
          className="flex items-center gap-1.5 text-sm text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Community
        </Link>
      </header>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4">
        <div className="mx-auto max-w-3xl space-y-3">
          {post.isLoading ? (
            <div className="surface shimmer h-56" aria-hidden="true" />
          ) : post.isError || !post.data ? (
            <div className="surface px-6 py-16 text-center">
              <h1 className="mb-1.5 text-md font-semibold text-fg">This post is not here</h1>
              <p className="text-base text-fg-muted">
                It was deleted, or the link is wrong.{' '}
                <Link href="/community" className="text-accent hover:underline">
                  Back to the board
                </Link>
                .
              </p>
            </div>
          ) : (
            <>
              <div ref={headingRef} tabIndex={-1} className="outline-none">
                <PostCard
                  post={post.data}
                  variant="detail"
                  onEdit={setEditing}
                  onDelete={handleDelete}
                  isDeleting={deletePost.isPending}
                />
              </div>

              <section className="surface p-4">
                <h2 className="label mb-3 flex items-center gap-1.5">
                  <MessageSquare className="h-3 w-3" />
                  {thread.data?.total ?? post.data.comments_count} replies
                </h2>

                {user ? (
                  <CommentComposer
                    isSubmitting={createComment.isPending}
                    onSubmit={(content) => createComment.mutateAsync({ content })}
                    placeholder="What do you make of it?"
                  />
                ) : (
                  <p className="rounded-md border border-line bg-surface-2 px-3 py-2.5 text-sm text-fg-subtle">
                    Sign in to join the thread.
                  </p>
                )}

                <div className="mt-4 border-t border-line pt-4">
                  {thread.isLoading ? (
                    <div className="shimmer h-24 rounded-md" aria-hidden="true" />
                  ) : (
                    <CommentThread
                      comments={thread.data?.comments ?? []}
                      postId={postId}
                      onReply={handleReply}
                      isReplying={createComment.isPending}
                    />
                  )}
                </div>
              </section>
            </>
          )}
        </div>
      </div>

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
