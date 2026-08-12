'use client';

import type { CommunityComment } from '@/lib/api';

import CommentItem from './CommentItem';

interface CommentThreadProps {
  comments: CommunityComment[];
  postId: string;
  onReply: (parentId: string, content: string) => Promise<unknown>;
  isReplying: boolean;
}

/**
 * The root of the reply forest.
 *
 * Thin on purpose: the recursion, collapsing and per-comment actions all live
 * in CommentItem, so this stays a list and nothing else.
 */
export default function CommentThread({
  comments,
  postId,
  onReply,
  isReplying,
}: CommentThreadProps) {
  if (comments.length === 0) {
    return (
      <p className="py-6 text-center text-base text-fg-subtle">
        No replies yet — be the one who adds something.
      </p>
    );
  }

  return (
    <ul className="space-y-0">
      {comments.map((comment) => (
        <CommentItem
          key={comment.id}
          comment={comment}
          postId={postId}
          onReply={onReply}
          isReplying={isReplying}
        />
      ))}
    </ul>
  );
}
