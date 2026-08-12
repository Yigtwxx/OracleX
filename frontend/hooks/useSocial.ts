'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  blockMember,
  fetchBlockedMembers,
  fetchCommunityActivity,
  fetchConversations,
  fetchDmEligibility,
  fetchMessages,
  fetchUnreadCount,
  fetchUserSettings,
  markConversationRead,
  sendMessage,
  startConversation,
  unblockMember,
  updateUserSettings,
  type DmMessage,
  type UserSettings,
} from '@/lib/api';
import { useOptionalAuth } from '@/contexts/AuthContext';
import { queryKeys } from '@/hooks/queries';

/**
 * Data for the Social tab.
 *
 * Freshness comes from polling rather than a socket. Nothing else in this app
 * holds a realtime subscription — `lib/supabase.ts` is used for auth only — and
 * a three-second poll on an open thread costs one small request against a
 * backend the same browser is already talking to, where a realtime channel
 * would mean the browser reading DM tables directly and RLS becoming the only
 * thing between one member and another's messages.
 *
 * Three cadences, each matched to what the user can actually perceive:
 *
 *   3s   an open thread — the one place a stale second is visible
 *   15s  the inbox
 *   20s  the nav badge
 */
const THREAD_POLL_MS = 3_000;
const INBOX_POLL_MS = 15_000;
const BADGE_POLL_MS = 20_000;

/** Forms on this tab render their own failures; skip the global toast. */
const SILENT = { silentError: true } as const;

function useUserId(): string | null {
  return useOptionalAuth().user?.id ?? null;
}

/**
 * Whether this account may start conversations, and what the rules are.
 *
 * Long `staleTime`: the answer only changes when the user verifies something or
 * their account gets old enough, and the mutations that could change it
 * invalidate this key themselves.
 */
export function useDmEligibility() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.socialEligibility,
    queryFn: fetchDmEligibility,
    enabled: Boolean(userId),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

export function useConversations() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.socialConversations,
    queryFn: fetchConversations,
    enabled: Boolean(userId),
    staleTime: 5 * 1000,
    refetchInterval: INBOX_POLL_MS,
    // Nothing arrives while the tab is hidden that the next foreground refetch
    // will not pick up, and a background poll on every open tab adds up.
    refetchIntervalInBackground: false,
    retry: false,
    // The inbox renders its own failure inline. Without this a poll that keeps
    // failing throws a "connection error" toast into the corner every fifteen
    // seconds, which says nothing about *which* surface is broken.
    meta: SILENT,
  });
}

/** One thread. Disabled until a conversation is selected. */
export function useMessages(conversationId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.socialMessages(conversationId ?? ''),
    queryFn: () => fetchMessages(conversationId as string),
    enabled: Boolean(conversationId),
    refetchInterval: THREAD_POLL_MS,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

/**
 * The number on the nav tab.
 *
 * `silentError` because a failed poll on a decoration must not put a toast on
 * screen every twenty seconds.
 */
export function useUnreadCount() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.socialUnread,
    queryFn: fetchUnreadCount,
    enabled: Boolean(userId),
    refetchInterval: BADGE_POLL_MS,
    refetchIntervalInBackground: false,
    retry: false,
    meta: SILENT,
  });
}

export function useCommunityActivity() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.socialActivity,
    queryFn: fetchCommunityActivity,
    enabled: Boolean(userId),
    staleTime: 60 * 1000,
    retry: false,
  });
}

export function useBlockedMembers() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.socialBlocks,
    queryFn: fetchBlockedMembers,
    enabled: Boolean(userId),
    staleTime: 60 * 1000,
    retry: false,
  });
}

/**
 * Open (or find) the thread with somebody.
 *
 * Throws `ApiError` carrying the unmet requirements when the gate refuses; the
 * caller reads them with `dmRefusalReasons`.
 */
export function useStartConversation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) => startConversation(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.socialConversations });
    },
    meta: SILENT,
  });
}

export function useSendMessage(conversationId: string | undefined) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: string) => sendMessage(conversationId as string, body),
    onSuccess: (message: DmMessage) => {
      // Appended straight into the thread rather than invalidated: the poll is
      // three seconds away and watching your own message take that long to
      // appear reads as a dropped send. Guarded against the poll having landed
      // first, which would otherwise duplicate the bubble.
      queryClient.setQueryData<DmMessage[]>(
        queryKeys.socialMessages(message.conversation_id),
        (previous) => {
          if (!previous) return [message];
          return previous.some((existing) => existing.id === message.id)
            ? previous
            : [...previous, message];
        }
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.socialConversations });
    },
    meta: SILENT,
  });
}

/**
 * Advance the read cursor.
 *
 * Both counters are corrected locally as well as invalidated, so opening a
 * thread clears its pill immediately instead of on the next poll.
 */
export function useMarkRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (conversationId: string) => markConversationRead(conversationId),
    onSuccess: (_result, conversationId) => {
      queryClient.setQueryData<number>(queryKeys.socialUnread, (previous) => {
        if (typeof previous !== 'number') return previous;
        const conversations = queryClient.getQueryData<{ id: string; unread_count: number }[]>(
          queryKeys.socialConversations
        );
        const cleared = conversations?.find((row) => row.id === conversationId)?.unread_count ?? 0;
        return Math.max(0, previous - cleared);
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.socialConversations });
      queryClient.invalidateQueries({ queryKey: queryKeys.socialUnread });
    },
    meta: SILENT,
  });
}

export function useUserSettings() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.userSettings,
    queryFn: fetchUserSettings,
    enabled: Boolean(userId),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

/**
 * Save a settings change.
 *
 * Invalidates the DM gate as well as the settings row: turning your own inbox
 * off does not change whether *you* may send, but it does change what the
 * Social tab should be telling you, and a stale five-minute verdict would
 * outlive the toggle.
 */
export function useUpdateUserSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (update: Partial<UserSettings>) => updateUserSettings(update),
    onSuccess: (_result, update) => {
      queryClient.setQueryData<UserSettings>(queryKeys.userSettings, (previous) =>
        previous ? { ...previous, ...update } : previous
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.userSettings });
      queryClient.invalidateQueries({ queryKey: queryKeys.socialEligibility });
    },
    meta: SILENT,
  });
}

export function useBlockMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) => blockMember(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.socialBlocks });
      queryClient.invalidateQueries({ queryKey: queryKeys.socialConversations });
    },
    meta: SILENT,
  });
}

export function useUnblockMember() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) => unblockMember(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.socialBlocks });
      queryClient.invalidateQueries({ queryKey: queryKeys.socialConversations });
    },
    meta: SILENT,
  });
}
