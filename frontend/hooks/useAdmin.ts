'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  adminDeleteComment,
  adminDeletePost,
  banAdminUser,
  fetchAdminAudit,
  fetchAdminOverview,
  fetchAdminPosts,
  fetchAdminSession,
  fetchAdminUsers,
  setAdminUserPlan,
  unbanAdminUser,
  type AdminUserListParams,
} from '@/lib/api';
import { useOptionalAuth } from '@/contexts/AuthContext';
import { showToast } from '@/lib/queryClient';
import { queryKeys } from '@/hooks/queries';

/** Admin mutations report their own failures, so they skip the global toast. */
const SILENT = { silentError: true } as const;

export const USERS_PAGE_SIZE = 50;
export const POSTS_PAGE_SIZE = 25;
export const AUDIT_PAGE_SIZE = 50;

/**
 * Whether the signed-in caller gets the admin panel.
 *
 * `enabled` on a session is not optional: signed out this would 401, and the
 * global handler in lib/queryClient.ts would raise a connection toast on every
 * page load for every anonymous visitor. `retry: false` for the same reason —
 * an authorization answer is not a transient failure worth three attempts.
 *
 * `useOptionalAuth` rather than `useAuth` because the nav renders this hook and
 * may mount outside the provider.
 */
export function useIsAdmin() {
  const { user } = useOptionalAuth();

  return useQuery({
    queryKey: queryKeys.adminSession,
    queryFn: fetchAdminSession,
    enabled: Boolean(user),
    retry: false,
    staleTime: Infinity,
    meta: SILENT,
  });
}

export function useAdminOverview(enabled = true) {
  return useQuery({
    queryKey: queryKeys.adminOverview,
    queryFn: fetchAdminOverview,
    enabled,
    retry: false,
    staleTime: 30 * 1000,
    meta: SILENT,
  });
}

export function useAdminUsers(params: AdminUserListParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.adminUsers(JSON.stringify(params)),
    queryFn: () => fetchAdminUsers(params),
    enabled,
    retry: false,
    staleTime: 15 * 1000,
    meta: SILENT,
  });
}

export function useAdminPosts(
  params: { search?: string; limit?: number; offset?: number },
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.adminPosts(JSON.stringify(params)),
    queryFn: () => fetchAdminPosts(params),
    enabled,
    retry: false,
    staleTime: 15 * 1000,
    meta: SILENT,
  });
}

export function useAdminAudit(offset = 0, enabled = true) {
  return useQuery({
    queryKey: queryKeys.adminAudit(offset),
    queryFn: () => fetchAdminAudit({ offset, limit: AUDIT_PAGE_SIZE }),
    enabled,
    retry: false,
    staleTime: 15 * 1000,
    meta: SILENT,
  });
}

/**
 * Invalidate everything an admin action can change.
 *
 * A ban does not alter the audit log's *page*, but it does add a row to it, and
 * the overview counts move with almost every action — so one helper rather than
 * a different partial list at each call site.
 */
function useAdminInvalidator() {
  const queryClient = useQueryClient();

  return () => {
    queryClient.invalidateQueries({ queryKey: ['adminUsers'] });
    queryClient.invalidateQueries({ queryKey: ['adminPosts'] });
    queryClient.invalidateQueries({ queryKey: ['adminAudit'] });
    queryClient.invalidateQueries({ queryKey: queryKeys.adminOverview });
  };
}

export function useSetUserPlan() {
  const invalidate = useAdminInvalidator();

  return useMutation({
    meta: SILENT,
    mutationFn: ({
      userId,
      plan,
      durationDays,
    }: {
      userId: string;
      plan: string;
      durationDays?: number;
    }) => setAdminUserPlan(userId, plan, durationDays),
    onSuccess: (user) => {
      invalidate();
      showToast(`${user.email ?? 'User'} is now on ${user.subscription_plan}`);
    },
    onError: () => showToast('Could not change the plan'),
  });
}

export function useBanUser() {
  const invalidate = useAdminInvalidator();

  return useMutation({
    meta: SILENT,
    mutationFn: ({ userId, days, reason }: { userId: string; days?: number; reason?: string }) =>
      banAdminUser(userId, { days, reason }),
    onSuccess: (user) => {
      invalidate();
      showToast(`${user.email ?? 'User'} suspended`);
    },
    onError: (error) => showToast(errorMessage(error, 'Could not suspend the account')),
  });
}

export function useUnbanUser() {
  const invalidate = useAdminInvalidator();

  return useMutation({
    meta: SILENT,
    mutationFn: (userId: string) => unbanAdminUser(userId),
    onSuccess: (user) => {
      invalidate();
      showToast(`${user.email ?? 'User'} reinstated`);
    },
    onError: () => showToast('Could not lift the suspension'),
  });
}

/**
 * Moderator delete.
 *
 * Invalidates the community caches as well as the admin ones: the same post is
 * on the board the admin just came from, and leaving it there is how a
 * moderator ends up deleting it twice.
 */
export function useAdminDeletePost() {
  const queryClient = useQueryClient();
  const invalidate = useAdminInvalidator();

  return useMutation({
    meta: SILENT,
    mutationFn: ({ postId, reason }: { postId: string; reason?: string }) =>
      adminDeletePost(postId, reason),
    onSuccess: (_result, { postId }) => {
      queryClient.removeQueries({ queryKey: queryKeys.communityPost(postId) });
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.communitySidebar });
      invalidate();
      showToast('Post removed');
    },
    onError: () => showToast('Could not remove the post'),
  });
}

export function useAdminDeleteComment(postId?: string) {
  const queryClient = useQueryClient();
  const invalidate = useAdminInvalidator();

  return useMutation({
    meta: SILENT,
    mutationFn: ({ commentId, reason }: { commentId: string; reason?: string }) =>
      adminDeleteComment(commentId, reason),
    onSuccess: () => {
      if (postId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.communityComments(postId) });
        queryClient.invalidateQueries({ queryKey: queryKeys.communityPost(postId) });
      }
      queryClient.invalidateQueries({ queryKey: ['communityFeed'] });
      invalidate();
      showToast('Comment removed');
    },
    onError: () => showToast('Could not remove the comment'),
  });
}

/** Surface the server's own message when it sent one — a 409 explains itself. */
function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
