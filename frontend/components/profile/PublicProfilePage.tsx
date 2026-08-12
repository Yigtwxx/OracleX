'use client';

import { ArrowBigUp, CalendarDays } from 'lucide-react';

import AuthCard from '@/components/auth/AuthCard';
import SocialIconRow from '@/components/profile/SocialIconRow';
import MessageButton from '@/components/social/MessageButton';
// PlanBadge is a named export of PostMeta, not its own module.
import { PlanBadge } from '@/components/community/PostMeta';
import { useAuth } from '@/contexts/AuthContext';
import { usePublicProfile } from '@/hooks/useProfile';

/**
 * Somebody else's profile.
 *
 * Signed-in only. A logged-out fetch would put every member's name, bio and
 * handles within reach of anything that can make an HTTP request, and the
 * community these pages belong to already sits behind a session. The backend
 * enforces this too — this is the polite half.
 *
 * Nothing here is verified. The handles are what the person typed, and the page
 * says so in words rather than implying the opposite with a badge.
 */
export default function PublicProfilePage({ userId }: { userId: string }) {
  const { user, loading: authLoading } = useAuth();
  const { data: profile, isLoading, isError } = usePublicProfile(user ? userId : undefined);

  if (authLoading) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="surface shimmer h-40 w-full max-w-sm" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="custom-scrollbar h-full overflow-y-auto p-6">
        <div className="flex min-h-full items-center justify-center">
          <AuthCard />
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="custom-scrollbar h-full overflow-y-auto p-4">
        <div className="surface shimmer mx-auto h-56 w-full max-w-2xl" />
      </div>
    );
  }

  if (isError || !profile) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <p className="text-base text-fg-muted">There is no profile here.</p>
      </div>
    );
  }

  const joined = profile.created_at
    ? new Date(profile.created_at).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'long',
      })
    : null;

  const initial = (profile.full_name ?? '').trim().charAt(0).toUpperCase() || '?';

  return (
    <div className="custom-scrollbar h-full overflow-y-auto p-4">
      <div className="mx-auto w-full max-w-2xl">
        <div className="surface p-5">
          <div className="flex items-start gap-4">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-line bg-surface-2 text-2xl text-fg-muted">
              {profile.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={profile.avatar_url} alt="" className="h-full w-full object-cover" />
              ) : (
                initial
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl text-fg">{profile.full_name || 'Anonymous'}</h1>
                <PlanBadge plan={profile.subscription_plan} />
              </div>

              <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-fg-subtle">
                <span className="flex items-center gap-1">
                  <ArrowBigUp className="h-4 w-4" />
                  <span className="text-fg-muted">{profile.karma.total_karma}</span>
                  karma
                  <span>
                    ({profile.karma.post_karma} post · {profile.karma.comment_karma} comment)
                  </span>
                </span>
                {joined && (
                  <span className="flex items-center gap-1">
                    <CalendarDays className="h-3.5 w-3.5" />
                    Joined {joined}
                  </span>
                )}
              </div>

              {profile.bio && (
                <p className="mt-3 whitespace-pre-wrap text-base text-fg-muted">{profile.bio}</p>
              )}

              {/* Renders nothing on your own profile, and nothing signed out. */}
              <div className="mt-3">
                <MessageButton userId={userId} viewerId={user.id} />
              </div>
            </div>
          </div>

          {profile.social_links.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <SocialIconRow links={profile.social_links} />
              <p className="mt-2 text-sm text-fg-subtle">
                Added by this person. Oracle-X has not verified them.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
