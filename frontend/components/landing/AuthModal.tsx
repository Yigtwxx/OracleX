'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import AuthCard, { type AuthMode } from '@/components/auth/AuthCard';
import Modal from '@/components/ui/Modal';
import { useAuth } from '@/contexts/AuthContext';

interface AuthModalProps {
  mode: AuthMode | null;
  onClose: () => void;
  /** Focus returns here on close — the button that opened the dialog. */
  returnFocusTo?: HTMLElement | null;
}

const TITLES: Record<AuthMode, string> = {
  signin: 'Sign in',
  signup: 'Create account',
  forgot: 'Reset password',
};

export default function AuthModal({ mode, onClose, returnFocusTo }: AuthModalProps) {
  const paneRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { user } = useAuth();
  const open = mode !== null;

  // The forms have no success callback — they rely on Supabase's
  // onAuthStateChange — so the modal watches the context instead. A sign-up that
  // still needs email confirmation leaves `user` null, which correctly keeps the
  // dialog on its "check your inbox" state rather than navigating away.
  useEffect(() => {
    if (!open || !user) return;
    onClose();
    router.push('/home');
  }, [open, user, onClose, router]);

  // Modal supplies the scrim, Escape and the scroll lock but no focus handling,
  // so the dialog moves focus in and hands it back here rather than changing
  // shared behaviour for every other modal in the app.
  useEffect(() => {
    if (!open) return;
    paneRef.current?.focus();
    return () => returnFocusTo?.focus();
  }, [open, returnFocusTo]);

  if (!open) return null;

  return (
    <Modal isOpen onClose={onClose} title={TITLES[mode]} maxWidth="max-w-sm">
      <div ref={paneRef} tabIndex={-1} className="p-4 outline-none">
        <AuthCard initialMode={mode} variant="modal" />
      </div>
    </Modal>
  );
}
