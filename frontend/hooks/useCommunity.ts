'use client';

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query';

import {
  createCommunityComment,
  createCommunityPost,
  deleteCommunityComment,
  deleteCommunityPost,
  fetchCommunityComments,
  fetchCommunityFeed,
  fetchCommunityPost,
  fetchCommunitySidebar,
  fetchUserCommunityPosts,
  updateCommunityComment,
  updateCommunityPost,
  voteOnCommunityComment,
  voteOnCommunityPost,
  type CommunityComment,
  type CommunityCommentThread,
  type CommunityFeedPage,
  type CommunityFeedSort,
  type CommunityPost,
  type CommunityPostType,
  type CreateCommunityPostInput,
  type UpdateCommunityPostInput,
} from '@/lib/api';
import { showToast } from '@/lib/queryClient';
import { queryKeys } from '@/hooks/queries';

export const PAGE_SIZE = 20;

/**
 * Community mutations report their own failures in English, so they opt out of
 * the global (Turkish) error toast in lib/queryClient.ts.
 */
const SILENT = { silentError: true } as const;

export interface FeedFilters {
  sort: CommunityFeedSort;
  type: CommunityPostType | 'all';
  symbol?: string;
  /** Set to a user id to show only that author's posts. */
  authorId?: string;
}

type FeedData = InfiniteData<CommunityFeedPage, number>;

function feedKey(filters: FeedFilters) {
  return queryKeys.communityFeed(
    filters.sort,
    filters.type,
    filters.authorId ?? 'all',
    filters.symbol
  );
}

// ── Reads ────────────────────────────────────────────────────────────────────

export function useCommunityFeed(filters: FeedFilters) {
  return useInfiniteQuery({
    queryKey: feedKey(filters),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      filters.authorId
        ? fetchUserCommunityPosts(filters.authorId, { limit: PAGE_SIZE, offset: pageParam })
        : fetchCommunityFeed({
            sort: filters.sort,
            type: filters.type,
            symbol: filters.symbol,
            limit: PAGE_SIZE,
            offset: pageParam,
          }),
    // Offset pagination, so the next cursor is however many rows we already hold.
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more
        ? allPages.reduce((total, page) => total + page.posts.length, 0)
        : undefined,
    staleTime: 30 * 1000,
  });
}

export function useCommunityPost(postId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.communityPost(postId ?? ''),
    queryFn: () => fetchCommunityPost(postId as string),
    enabled: Boolean(postId),
    staleTime: 30 * 1000,
  });
}

export function useCommunityComments(postId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.communityComments(postId ?? ''),
    queryFn: () => fetchCommunityComments(postId as string),
    enabled: Boolean(postId),
    staleTime: 15 * 1000,
  });
}

export function useCommunitySidebar() {
  return useQuery({
    queryKey: queryKeys.communitySidebar,
    queryFn: fetchCommunitySidebar,
    staleTime: 5 * 60 * 1000,
  });
}

// ── Voting ───────────────────────────────────────────────────────────────────

/**
 * Reddit's toggle rule: clicking the arrow you already chose clears the vote.
 * Returns the value to send, which is 0 for a repeat click.
 */
export function nextVoteValue(current: number, clicked: 1 | -1): number {
  return current === clicked ? 0 : clicked;
}

function applyPostVote(post: CommunityPost, value: number): CommunityPost {
  // The score moves by the *difference* between the old and new vote, so
  // flipping an upvote to a downvote is a swing of two, not one.
  return { ...post, score: post.score - post.my_vote + value, my_vote: value };
}

function patchCommentTree(
  comments: CommunityComment[],
  commentId: string,
  patch: (comment: CommunityComment) => CommunityComment
): CommunityComment[] {
  return comments.map((comment) => {
    if (comment.id === commentId) return patch(comment);
    if (comment.replies.length === 0) return comment;
    return { ...comment, replies: patchCommentTree(comment.replies, commentId, patch) };
  });
}

/**
 * Vote on a post, updating every cache that holds it before the request lands.
 *
 * The post can be on screen twice at once — in a feed page and on its own
 * detail route — so both are patched, and both are rolled back together if the
 * write fails.
 */
export function useVoteOnPost() {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: ({ postId, value }: { postId: string; value: number }) =>
      voteOnCommunityPost(postId, value),

    onMutate: async ({ postId, value }) => {
      await queryClient.cancelQueries({ queryKey: ['communityFeed'] });
      await queryClient.cancelQueries({ queryKey: queryKeys.communityPost(postId) });

      const feeds = queryClient.getQueriesData<FeedData>({ queryKey: ['communityFeed'] });
      const detail = queryClient.getQueryData<CommunityPost>(queryKeys.communityPost(postId));

      for (const [key, data] of feeds) {
        if (!data) continue;
        queryClient.setQueryData<FeedData>(key, {
          ...data,
          pages: data.pages.map((page) => ({
            ...page,
            posts: page.posts.map((post) =>
              post.id === postId ? applyPostVote(post, value) : post
            ),
          })),
        });
      }

      if (detail) {
        queryClient.setQueryData(queryKeys.communityPost(postId), applyPostVote(detail, value));
      }

      return { feeds, detail };
    },

    onError: (_error, { postId }, context) => {
      context?.feeds.forEach(([key, data]) => queryClient.setQueryData(key, data));
      if (context?.detail) {
        queryClient.setQueryData(queryKeys.communityPost(postId), context.detail);
      }
      showToast('Could not save your vote');
    },

    onSuccess: (result, { postId }) => {
      // The server recomputed the score from the vote table, including anything
      // that landed at the same time. Write it rather than refetching.
      const write = (post: CommunityPost) => ({
        ...post,
        score: result.score,
        my_vote: result.my_vote,
      });

      queryClient.setQueriesData<FeedData>({ queryKey: ['communityFeed'] }, (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                posts: page.posts.map((post) => (post.id === postId ? write(post) : post)),
              })),
            }
          : data
      );
      queryClient.setQueryData<CommunityPost>(queryKeys.communityPost(postId), (post) =>
        post ? write(post) : post
      );
    },
  });
}

export function useVoteOnComment(postId: string) {
  const queryClient = useQueryClient();
  const key = queryKeys.communityComments(postId);

  return useMutation({
    meta: SILENT,
    mutationFn: ({ commentId, value }: { commentId: string; value: number }) =>
      voteOnCommunityComment(commentId, value),

    onMutate: async ({ commentId, value }) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<CommunityCommentThread>(key);

      if (previous) {
        queryClient.setQueryData<CommunityCommentThread>(key, {
          ...previous,
          comments: patchCommentTree(previous.comments, commentId, (comment) => ({
            ...comment,
            score: comment.score - comment.my_vote + value,
            my_vote: value,
          })),
        });
      }

      return { previous };
    },

    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous);
      showToast('Could not save your vote');
    },

    onSuccess: (result, { commentId }) => {
      queryClient.setQueryData<CommunityCommentThread>(key, (thread) =>
        thread
          ? {
              ...thread,
              comments: patchCommentTree(thread.comments, commentId, (comment) => ({
                ...comment,
                score: result.score,
                my_vote: result.my_vote,
              })),
            }
          : thread
      );
    },
  });
}

// ── Posts ────────────────────────────────────────────────────────────────────

export function useCreatePost() {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: (input: CreateCommunityPostInput) => createCommunityPost(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.communitySidebar });
    },
    onError: () => showToast('Could not publish your post'),
  });
}

export function useUpdatePost() {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: ({ postId, patch }: { postId: string; patch: UpdateCommunityPostInput }) =>
      updateCommunityPost(postId, patch),
    onSuccess: (post) => {
      queryClient.setQueryData(queryKeys.communityPost(post.id), post);
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
    },
    onError: () => showToast('Could not save your changes'),
  });
}

export function useDeletePost() {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: (postId: string) => deleteCommunityPost(postId),
    onSuccess: (_result, postId) => {
      queryClient.removeQueries({ queryKey: queryKeys.communityPost(postId) });
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.communitySidebar });
    },
    onError: () => showToast('Could not delete the post'),
  });
}

// ── Comments ─────────────────────────────────────────────────────────────────

export function useCreateComment(postId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: (input: { content: string; parentId?: string }) =>
      createCommunityComment(postId, { content: input.content, parent_id: input.parentId }),
    onSuccess: () => {
      // Refetched rather than spliced in: the reply needs its author joined on,
      // and the post's comment counter has moved too.
      queryClient.invalidateQueries({ queryKey: queryKeys.communityComments(postId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.communityPost(postId) });
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
    },
    onError: (error) =>
      showToast(
        error instanceof Error && error.message.includes('400')
          ? 'Replies are limited to four levels deep'
          : 'Could not post your reply'
      ),
  });
}

export function useUpdateComment(postId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: ({ commentId, content }: { commentId: string; content: string }) =>
      updateCommunityComment(commentId, content),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.communityComments(postId) });
    },
    onError: () => showToast('Could not save your edit'),
  });
}

export function useDeleteComment(postId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    meta: SILENT,
    mutationFn: (commentId: string) => deleteCommunityComment(commentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.communityComments(postId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.communityPost(postId) });
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
    },
    onError: () => showToast('Could not delete the comment'),
  });
}
