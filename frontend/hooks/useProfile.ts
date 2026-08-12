'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  deleteAccount,
  deleteAvatar,
  fetchProfile,
  fetchPublicProfile,
  updateProfile,
  updateSocialLinks,
  uploadAvatar,
  type Profile,
  type SocialLinkInput,
} from '@/lib/api';
import { useOptionalAuth } from '@/contexts/AuthContext';
import { queryKeys } from '@/hooks/queries';

/**
 * Every form on the profile page renders its own failure inline, so these skip
 * the global toast in lib/queryClient.ts — otherwise a failed save says so
 * twice, once in the form and once in a corner of the screen.
 */
const SILENT = { silentError: true } as const;

/** The signed-in user's id, or `null`. Also the gate on every query below. */
function useUserId(): string | null {
  return useOptionalAuth().user?.id ?? null;
}

export function useProfile() {
  const userId = useUserId();

  return useQuery({
    queryKey: queryKeys.profile(userId ?? 'anonymous'),
    queryFn: fetchProfile,
    // Signed out this would 401 on every page load. `retry: false` for the same
    // reason it is set on the admin session: an authorization answer is not a
    // transient failure worth three attempts.
    enabled: Boolean(userId),
    retry: false,
    staleTime: 30 * 1000,
    meta: SILENT,
  });
}

/** Somebody else's profile, for `/u/{id}`. Gated on the *viewer* being signed in. */
export function usePublicProfile(userId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.publicProfile(userId ?? 'none'),
    queryFn: () => fetchPublicProfile(userId as string),
    enabled: Boolean(userId),
    retry: false,
    staleTime: 60 * 1000,
    meta: SILENT,
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  const userId = useUserId();

  return useMutation({
    // Photo changes go through useUploadAvatar/useDeleteAvatar, which own the
    // bucket as well as the column; this is for the editable text fields.
    mutationFn: (update: { full_name?: string; bio?: string }) => updateProfile(update),
    onSuccess: (_data, update) => {
      // Patch the cache rather than refetching: the server accepted exactly the
      // fields we sent, and a round-trip here makes the name flicker back to
      // its old value before settling.
      queryClient.setQueryData<Profile>(queryKeys.profile(userId ?? 'anonymous'), (prev) =>
        prev ? { ...prev, ...update } : prev
      );
    },
    meta: SILENT,
  });
}

export function useUploadAvatar() {
  const queryClient = useQueryClient();
  const userId = useUserId();

  return useMutation({
    mutationFn: (file: File) => uploadAvatar(file),
    onSuccess: ({ url }) => {
      queryClient.setQueryData<Profile>(queryKeys.profile(userId ?? 'anonymous'), (prev) =>
        prev ? { ...prev, avatar_url: url } : prev
      );
    },
    meta: SILENT,
  });
}

export function useDeleteAvatar() {
  const queryClient = useQueryClient();
  const userId = useUserId();

  return useMutation({
    mutationFn: deleteAvatar,
    onSuccess: () => {
      queryClient.setQueryData<Profile>(queryKeys.profile(userId ?? 'anonymous'), (prev) =>
        prev ? { ...prev, avatar_url: undefined } : prev
      );
    },
    meta: SILENT,
  });
}

export function useUpdateSocialLinks() {
  const queryClient = useQueryClient();
  const userId = useUserId();

  return useMutation({
    mutationFn: (links: SocialLinkInput[]) => updateSocialLinks(links),
    onSuccess: ({ links }) => {
      // The server normalises handles and derives every URL, so take its answer
      // rather than the payload we sent — the two are not always identical.
      queryClient.setQueryData<Profile>(queryKeys.profile(userId ?? 'anonymous'), (prev) =>
        prev ? { ...prev, social_links: links } : prev
      );
      if (userId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.publicProfile(userId) });
      }
    },
    meta: SILENT,
  });
}

export function useDeleteAccount() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (confirmEmail: string) => deleteAccount(confirmEmail),
    onSuccess: () => {
      // The account is gone; anything still cached about it is a lie.
      queryClient.clear();
    },
    meta: SILENT,
  });
}
