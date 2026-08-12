'use client';

import { BadgeCheck, LogOut, User as UserIcon } from 'lucide-react';

import { useAuth } from '@/contexts/AuthContext';
import type { Profile } from '@/lib/api';
import type { User } from '@supabase/supabase-js';

interface ProfileHeaderProps {
  user: User;
  profile: Profile | undefined;
}

const PLAN_LABEL: Record<string, string> = {
  free: 'Free',
  pro: 'Pro',
  whale: 'Whale',
};

export default function ProfileHeader({ user, profile }: ProfileHeaderProps) {
  const { signOut } = useAuth();
  const displayName = profile?.full_name || user.email?.split('@')[0] || 'Account';
  const plan = profile?.subscription_plan ?? 'free';
  const verified = Boolean(user.email_confirmed_at);

  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <div className="h-10 w-10 shrink-0 overflow-hidden rounded-full border border-line bg-surface-2">
          {profile?.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- see AvatarField
            <img src={profile.avatar_url} alt="" className="h-full w-full object-cover" />
          ) : (
            <span className="flex h-full w-full items-center justify-center">
              <UserIcon className="h-4 w-4 text-fg-subtle" />
            </span>
          )}
        </div>

        <div className="min-w-0">
          <h1 className="truncate text-md font-semibold text-fg">{displayName}</h1>
          <p className="flex items-center gap-1.5 text-xs text-fg-subtle">
            <span className="truncate">{user.email}</span>
            {verified && (
              <BadgeCheck
                className="h-3 w-3 shrink-0 text-up"
                aria-label="Email confirmed"
                role="img"
              />
            )}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="rounded border border-line px-1.5 py-0.5 text-2xs uppercase tracking-wide text-fg-muted">
              {PLAN_LABEL[plan] ?? plan} plan
            </span>
            {profile && profile.ai_query_limit < 1000 && (
              <span className="rounded border border-line px-1.5 py-0.5 font-mono text-2xs tabnum text-fg-subtle">
                AI {profile.ai_queries_today}/{profile.ai_query_limit}
              </span>
            )}
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={() => signOut()}
        className="flex shrink-0 items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-down hover:text-down"
      >
        <LogOut className="h-3.5 w-3.5" />
        Sign out
      </button>
    </header>
  );
}
