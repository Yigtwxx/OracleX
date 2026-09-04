'use client';

import { Loader2, MessagesSquare, User, X } from 'lucide-react';

import ProfileCard from '@/components/profile/ProfileCard';
import {
  useBlockedMembers,
  useUnblockMember,
  useUpdateUserSettings,
  useUserSettings,
} from '@/hooks/useSocial';

/**
 * Who is allowed to message you.
 *
 * Two controls that answer the same question at different scopes: the switch
 * closes the inbox to everybody, the list reopens it to everybody except the
 * people on it. Both live here rather than on the Social tab because they are
 * settings, and Social is where the messages are.
 */
export default function MessagingCard() {
  const { data: settings, isLoading } = useUserSettings();
  const update = useUpdateUserSettings();
  const { data: blocked } = useBlockedMembers();
  const unblock = useUnblockMember();

  // Defaults to on while loading, matching the column default — a switch that
  // renders off and then flips on reads as having been changed by the page.
  const enabled = settings?.dm_enabled ?? true;

  return (
    <ProfileCard title="Messaging" icon={MessagesSquare}>
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-base text-fg">Accept direct messages</p>
            <p className="mt-0.5 text-sm text-fg-subtle">
              When this is off, nobody can start a conversation with you or send into an existing
              one. Threads you are already in stay readable.
            </p>
          </div>

          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            aria-label="Accept direct messages"
            disabled={isLoading || update.isPending}
            onClick={() => update.mutate({ dm_enabled: !enabled })}
            className={`relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              enabled ? 'bg-accent' : 'bg-surface-2 border border-line'
            }`}
          >
            <span
              className={`absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                enabled ? 'translate-x-[1.125rem]' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        {update.isError && (
          <p className="text-sm text-down">That did not save. Try again in a moment.</p>
        )}

        <div className="border-t border-line pt-4">
          <p className="text-base text-fg">Blocked</p>
          {!blocked || blocked.length === 0 ? (
            <p className="mt-0.5 text-sm text-fg-subtle">
              You have not blocked anyone. Block someone from the menu at the top of a conversation.
            </p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {blocked.map((member) => (
                <li key={member.user_id} className="flex items-center gap-2.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full border border-line bg-surface-2">
                    {member.avatar_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={member.avatar_url} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <User className="h-3 w-3 text-fg-subtle" />
                    )}
                  </div>
                  <span className="min-w-0 flex-1 truncate text-base text-fg-muted">
                    {member.full_name || 'Anonymous'}
                  </span>
                  <button
                    type="button"
                    onClick={() => unblock.mutate(member.user_id)}
                    disabled={unblock.isPending}
                    aria-label={`Unblock ${member.full_name || 'this member'}`}
                    className="flex shrink-0 items-center gap-1 rounded-md border border-line px-2 py-0.5 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
                  >
                    {unblock.isPending ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <X className="h-3 w-3" />
                    )}
                    Unblock
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </ProfileCard>
  );
}
