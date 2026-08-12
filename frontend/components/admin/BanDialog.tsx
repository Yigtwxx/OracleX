'use client';

import { useState } from 'react';

import Modal from '@/components/ui/Modal';
import type { AdminUser } from '@/lib/api';

const DURATIONS: { label: string; days?: number }[] = [
  { label: '1 day', days: 1 },
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: 'Permanent' },
];

interface BanDialogProps {
  user: AdminUser | undefined;
  isSubmitting?: boolean;
  onClose: () => void;
  onConfirm: (input: { days?: number; reason?: string }) => void;
}

/**
 * The suspension confirmation.
 *
 * A dialog rather than an inline toggle because a suspension blocks every
 * authenticated request the account can make, there is no undo beyond lifting
 * it, and the reason is what the audit trail will show months later. Same
 * reasoning as the two-click delete in PostMenu, one step further.
 */
export default function BanDialog({ user, isSubmitting, onClose, onConfirm }: BanDialogProps) {
  const [days, setDays] = useState<number | undefined>(7);
  const [reason, setReason] = useState('');

  if (!user) return null;

  return (
    <Modal isOpen onClose={onClose} title="Suspend account">
      {/* Modal's body has no padding of its own — each dialog owns its inset. */}
      <div className="space-y-4 p-4">
        <p className="text-base text-fg-muted">
          <span className="text-fg">{user.email ?? user.full_name ?? user.id}</span> will be refused
          on every signed-in request until the suspension lifts. Reading the site stays open to
          them.
        </p>

        <div>
          <div className="label mb-1.5">Duration</div>
          <div className="flex flex-wrap gap-1.5">
            {DURATIONS.map((option) => {
              const active = days === option.days;
              return (
                <button
                  key={option.label}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setDays(option.days)}
                  className={`rounded-md border px-2.5 py-1 text-base transition-colors ${
                    active
                      ? 'border-accent bg-accent-bg text-accent'
                      : 'border-line text-fg-muted hover:border-line-strong hover:text-fg'
                  }`}
                >
                  {option.label}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label htmlFor="ban-reason" className="label mb-1.5 block">
            Reason
          </label>
          <input
            id="ban-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={500}
            placeholder="Recorded in the audit log"
            className="w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg transition-colors placeholder:text-fg-subtle focus:border-accent focus:outline-none"
          />
        </div>

        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={isSubmitting}
            onClick={() => onConfirm({ days, reason: reason.trim() || undefined })}
            className="rounded-md bg-down px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {isSubmitting ? 'Suspending…' : days ? `Suspend for ${days}d` : 'Suspend permanently'}
          </button>
        </div>
      </div>
    </Modal>
  );
}
