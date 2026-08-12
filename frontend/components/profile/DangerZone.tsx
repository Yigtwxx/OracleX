'use client';

import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';

import DeleteAccountDialog from '@/components/profile/DeleteAccountDialog';
import ProfileCard from '@/components/profile/ProfileCard';

export default function DangerZone({ email }: { email: string }) {
  const [confirming, setConfirming] = useState(false);

  return (
    <>
      <ProfileCard title="Delete account" icon={AlertTriangle} tone="danger">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-md text-base text-fg-muted">
            Permanently erase this account and everything attached to it. There is no undo.
          </p>
          {/* Outline, not a solid fill. The solid `bg-down` is spent once, on
              the final confirm inside the dialog — a button that only opens a
              dialog has not earned it. */}
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="shrink-0 rounded-md border border-down bg-down-bg px-3 py-1.5 text-base text-down transition-opacity hover:opacity-90"
          >
            Delete account
          </button>
        </div>
      </ProfileCard>

      {confirming && <DeleteAccountDialog email={email} onClose={() => setConfirming(false)} />}
    </>
  );
}
