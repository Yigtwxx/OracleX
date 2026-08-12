'use client';

import { useEffect, useState } from 'react';
import { Loader2, MailWarning } from 'lucide-react';

import { useAuth } from '@/contexts/AuthContext';
import { friendlyAuthError } from '@/lib/auth-validation';

/** Supabase throttles its own sender; a second click inside a minute just fails. */
const COOLDOWN_SECONDS = 60;

/**
 * Shown while GoTrue has not confirmed the address.
 *
 * The app never read `email_confirmed_at` before, so an account stuck in this
 * state had no way to find out — and no way to ask for another link. Adminship
 * also requires a confirmed address (see dependencies/auth.py), which made this
 * silently the difference between having the admin tab and not.
 */
export default function EmailVerificationBanner({ email }: { email: string }) {
  const { resendConfirmation } = useAuth();
  const [cooldown, setCooldown] = useState(0);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const resend = async () => {
    setError('');
    setSent(false);
    setIsSending(true);
    try {
      const { error: resendError } = await resendConfirmation(email);
      if (resendError) {
        setError(friendlyAuthError(resendError));
        return;
      }
      setSent(true);
      setCooldown(COOLDOWN_SECONDS);
    } catch (err) {
      setError(friendlyAuthError(err));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="shrink-0 border-b border-warn/40 bg-warn-bg px-4 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-base text-warn">
          <MailWarning className="h-3.5 w-3.5 shrink-0" />
          {error
            ? error
            : sent
              ? `Confirmation link sent to ${email}.`
              : 'Your email is not confirmed yet. Some features stay locked until it is.'}
        </p>
        <button
          type="button"
          disabled={isSending || cooldown > 0}
          onClick={resend}
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-warn/60 px-2.5 py-1 text-base text-warn transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {isSending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend confirmation'}
        </button>
      </div>
    </div>
  );
}
