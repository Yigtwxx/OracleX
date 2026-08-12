'use client';

import { useCallback, useId, useState } from 'react';
import { CornerDownRight, Minus, Pencil, Plus, Trash2 } from 'lucide-react';

import Markdown from '@/components/ui/Markdown';
import { useAuth } from '@/contexts/AuthContext';
import { useAdminDeleteComment, useIsAdmin } from '@/hooks/useAdmin';
import {
  nextVoteValue,
  useDeleteComment,
  useUpdateComment,
  useVoteOnComment,
} from '@/hooks/useCommunity';
import { showToast } from '@/lib/queryClient';
import type { CommunityComment } from '@/lib/api';

import CommentComposer from './CommentComposer';
import VoteColumn from './VoteColumn';
import { Avatar, PlanBadge, relativeTime } from './PostMeta';

/** Mirrors community_comments_depth_check in migration 007. */
const MAX_DEPTH = 3;

interface CommentItemProps {
  comment: CommunityComment;
  postId: string;
  onReply: (parentId: string, content: string) => Promise<unknown>;
  isReplying: boolean;
}

function countDescendants(comment: CommunityComment): number {
  return comment.replies.reduce((total, reply) => total + 1 + countDescendants(reply), 0);
}

/**
 * One comment and everything under it.
 *
 * Recursive by design — depth is capped at four levels by the database, so the
 * recursion is bounded and does not need a guard of its own.
 */
export default function CommentItem({ comment, postId, onReply, isReplying }: CommentItemProps) {
  const { user } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [replying, setReplying] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const subtreeId = useId();
  const vote = useVoteOnComment(postId);
  const updateComment = useUpdateComment(postId);
  const deleteComment = useDeleteComment(postId);
  const { data: adminSession } = useIsAdmin();
  const moderatorDelete = useAdminDeleteComment(postId);

  const isOwner = Boolean(user && !comment.is_deleted && comment.author.id === user.id);
  const isModerator = Boolean(adminSession?.is_admin) && !isOwner && !comment.is_deleted;
  const hidden = countDescendants(comment);

  const handleVote = useCallback(
    (direction: 1 | -1) => {
      if (!user) {
        showToast('Sign in to vote');
        return;
      }
      vote.mutate({
        commentId: comment.id,
        value: nextVoteValue(comment.my_vote, direction),
      });
    },
    [user, vote, comment.id, comment.my_vote]
  );

  const actionClass =
    'flex items-center gap-1 text-xs text-fg-subtle transition-colors hover:text-fg';

  return (
    <li className="relative">
      <div className="flex gap-2">
        {/* The thread line doubles as the collapse target, the way Reddit's does. */}
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-expanded={!collapsed}
          aria-controls={subtreeId}
          aria-label={collapsed ? 'Expand this thread' : 'Collapse this thread'}
          className="group flex w-4 shrink-0 justify-center"
        >
          {collapsed ? (
            <Plus className="mt-1 h-3 w-3 text-fg-subtle group-hover:text-fg" />
          ) : (
            <span className="mt-1 block w-px flex-1 bg-line transition-colors group-hover:bg-line-strong" />
          )}
        </button>

        <div className="min-w-0 flex-1 pb-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-fg-subtle">
            {!comment.is_deleted && <Avatar author={comment.author} size={18} />}
            <span className={comment.is_deleted ? 'italic' : 'text-fg-muted'}>
              {comment.is_deleted ? '[deleted]' : comment.author.full_name || 'Anonymous'}
            </span>
            {!comment.is_deleted && <PlanBadge plan={comment.author.subscription_plan} />}
            <span aria-hidden="true">·</span>
            <time dateTime={comment.created_at}>{relativeTime(comment.created_at)}</time>
            {comment.is_edited && !comment.is_deleted && (
              <>
                <span aria-hidden="true">·</span>
                <span>edited</span>
              </>
            )}
            {collapsed && hidden > 0 && (
              <span className="text-fg-subtle">
                ({hidden} {hidden === 1 ? 'reply' : 'replies'} hidden)
              </span>
            )}
          </div>

          {!collapsed && (
            <div id={subtreeId}>
              {editing ? (
                <div className="mt-2">
                  <CommentComposer
                    initialValue={comment.content ?? ''}
                    submitLabel="Save"
                    isSubmitting={updateComment.isPending}
                    autoFocus
                    onCancel={() => setEditing(false)}
                    onSubmit={async (content) => {
                      await updateComment.mutateAsync({ commentId: comment.id, content });
                      setEditing(false);
                    }}
                  />
                </div>
              ) : (
                <div className="mt-1">
                  {comment.is_deleted ? (
                    <p className="text-base italic text-fg-subtle">
                      This comment was removed by its author.
                    </p>
                  ) : (
                    <Markdown content={comment.content ?? ''} variant="community" />
                  )}
                </div>
              )}

              {!comment.is_deleted && !editing && (
                <div className="mt-1.5 flex flex-wrap items-center gap-3">
                  <VoteColumn
                    score={comment.score}
                    myVote={comment.my_vote}
                    onVote={handleVote}
                    disabled={!user}
                    orientation="horizontal"
                  />

                  {comment.depth < MAX_DEPTH && (
                    <button
                      type="button"
                      className={actionClass}
                      onClick={() => {
                        if (!user) {
                          showToast('Sign in to reply');
                          return;
                        }
                        setReplying((value) => !value);
                      }}
                    >
                      <CornerDownRight className="h-3 w-3" />
                      Reply
                    </button>
                  )}

                  {isOwner && (
                    <button type="button" className={actionClass} onClick={() => setEditing(true)}>
                      <Pencil className="h-3 w-3" />
                      Edit
                    </button>
                  )}

                  {/* An admin gets the same two-click removal on anyone's
                      comment, routed to the moderator endpoint. No Edit —
                      rewriting someone else's words is a different act. */}
                  {(isOwner || isModerator) && (
                    <button
                      type="button"
                      className={`${actionClass} ${confirmingDelete ? 'text-down hover:text-down' : ''}`}
                      onClick={() => {
                        if (!confirmingDelete) {
                          setConfirmingDelete(true);
                          return;
                        }
                        if (isModerator) {
                          moderatorDelete.mutate({ commentId: comment.id });
                        } else {
                          deleteComment.mutate(comment.id);
                        }
                        setConfirmingDelete(false);
                      }}
                    >
                      <Trash2 className="h-3 w-3" />
                      {confirmingDelete ? 'Confirm' : isModerator ? 'Remove' : 'Delete'}
                    </button>
                  )}

                  {comment.depth === MAX_DEPTH && (
                    <span className="flex items-center gap-1 text-xs text-fg-subtle">
                      <Minus className="h-3 w-3" />
                      Nesting limit reached
                    </span>
                  )}
                </div>
              )}

              {replying && (
                <div className="mt-2">
                  <CommentComposer
                    placeholder={`Reply to ${comment.author.full_name || 'this comment'}`}
                    submitLabel="Reply"
                    isSubmitting={isReplying}
                    autoFocus
                    onCancel={() => setReplying(false)}
                    onSubmit={async (content) => {
                      await onReply(comment.id, content);
                      setReplying(false);
                    }}
                  />
                </div>
              )}

              {comment.replies.length > 0 && (
                <ul className="mt-3 space-y-0">
                  {comment.replies.map((reply) => (
                    <CommentItem
                      key={reply.id}
                      comment={reply}
                      postId={postId}
                      onReply={onReply}
                      isReplying={isReplying}
                    />
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
