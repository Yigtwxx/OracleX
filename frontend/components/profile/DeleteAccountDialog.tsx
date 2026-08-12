'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import { INPUT_CLASS, FormNotice } from '@/components/auth/AuthField';
import Modal from '@/components/ui/Modal';
import { useAuth } from '@/contexts/AuthContext';
import { useDeleteAccount } from '@/hooks/useProfile';

interface DeleteAccountDialogProps {
  email: string;
  onClose: () => void;
}

/**
 * The confirmation for an irreversible delete.
 *
 * Typing the address is not theatre: the backend requires the same string in
 * the request body, so a client that skips this dialog still has to prove the
 * call was deliberate. Same reasoning as BanDialog, one step further — a
 * suspension can be lifted and this cannot.
 */
export default function DeleteAccountDialog({ email, onClose }: DeleteAccountDialogProps) {
  const { signOut } = useAuth();
  const [typed, setTyped] = useState('');
  const [error, setError] = useState('');
  const remove = useDeleteAccount();

  const matches = typed.trim().toLowerCase() === email.trim().toLowerCase();

  const handleConfirm = async () => {
    setError('');
    try {
      await remove.mutateAsync(typed.trim());
      await signOut();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The account could not be deleted.');
    }
  };

  return (
    <Modal isOpen onClose={onClose} title="Delete account">
      {/* Modal's body has no padding of its own — each dialog owns its inset. */}
      <div className="space-y-4 p-4">
        <p className="text-base text-fg-muted">
          This erases your profile, watchlists, notes, chat history, saved AI provider key and every
          post and comment you have written. It cannot be undone and there is no backup.
        </p>

        <div>
          <label htmlFor="delete-confirm" className="label mb-1.5 block">
            Type <span className="font-mono text-fg-muted">{email}</span> to confirm
          </label>
          <input
            id="delete-confirm"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            className={INPUT_CLASS}
          />
        </div>

        {error && <FormNotice tone="error">{error}</FormNotice>}

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
            disabled={!matches || remove.isPending}
            onClick={handleConfirm}
            className="flex items-center gap-2 rounded-md bg-down px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {remove.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Delete permanently
          </button>
        </div>
      </div>
    </Modal>
  );
}
