'use client';

import { useState } from 'react';
import { Check, Loader2, Pencil, UserCircle, X } from 'lucide-react';

import AvatarField from '@/components/profile/AvatarField';
import BioField from '@/components/profile/BioField';
import ProfileCard, { Field } from '@/components/profile/ProfileCard';
import { INPUT_CLASS } from '@/components/auth/AuthField';
import { useUpdateProfile } from '@/hooks/useProfile';
import { validateFullName } from '@/lib/auth-validation';
import type { Profile } from '@/lib/api';
import type { User } from '@supabase/supabase-js';

interface IdentityCardProps {
  user: User;
  profile: Profile | undefined;
}

export default function IdentityCard({ user, profile }: IdentityCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const update = useUpdateProfile();

  const displayName = profile?.full_name || user.email?.split('@')[0] || '';

  const startEditing = () => {
    setName(profile?.full_name ?? '');
    setError('');
    setIsEditing(true);
  };

  const save = async () => {
    const trimmed = name.trim();
    const nameError = validateFullName(trimmed);
    if (nameError) {
      setError(nameError);
      return;
    }

    try {
      await update.mutateAsync({ full_name: trimmed });
      setIsEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save your name.');
    }
  };

  return (
    <ProfileCard
      title="Account"
      icon={UserCircle}
      action={
        isEditing ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setIsEditing(false)}
              aria-label="Cancel"
              className="rounded-md p-1 text-fg-muted transition-colors hover:text-fg"
            >
              <X className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              disabled={update.isPending}
              onClick={save}
              className="flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {update.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Save
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={startEditing}
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </button>
        )
      }
    >
      <div className="space-y-4">
        <AvatarField url={profile?.avatar_url} displayName={displayName} />

        <div className="space-y-2.5 border-t border-line pt-4">
          <Field label="Name">
            {isEditing ? (
              <>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && save()}
                  aria-label="Full name"
                  autoFocus
                  className={INPUT_CLASS}
                />
                {error && <p className="mt-1 text-sm text-down">{error}</p>}
              </>
            ) : (
              profile?.full_name || <span className="text-fg-subtle">Not set</span>
            )}
          </Field>

          {/* Read-only. Changing the address on a Supabase account means
              re-confirming it from both mailboxes; until that flow exists,
              showing an editable box here would be a promise we do not keep. */}
          <Field label="Email">
            <span className="break-all">{user.email}</span>
          </Field>

          <Field label="User ID">
            <span className="block truncate font-mono text-sm text-fg-muted">{user.id}</span>
          </Field>

          <Field label="Member since">
            {new Date(user.created_at).toLocaleDateString(undefined, {
              year: 'numeric',
              month: 'long',
              day: 'numeric',
            })}
          </Field>
        </div>

        {/* Outside the Edit toggle above: the bio owns its own dirty state and
            save button, so gating it behind the name editor would mean two
            different ways to save one card. */}
        <div className="border-t border-line pt-4">
          <BioField
            value={profile?.bio ?? ''}
            onSave={async (bio) => {
              await update.mutateAsync({ bio });
            }}
          />
        </div>
      </div>
    </ProfileCard>
  );
}
