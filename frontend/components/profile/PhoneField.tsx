'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, Phone } from 'lucide-react';

import ProfileCard from '@/components/profile/ProfileCard';
import { INPUT_CLASS } from '@/components/auth/AuthField';
import { getSupabase } from '@/lib/supabase';
import { isValidOtp, isValidPhone, normalisePhone } from '@/lib/social';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/hooks/queries';
import type { User } from '@supabase/supabase-js';

/**
 * Add and verify a phone number.
 *
 * Runs against the Supabase client rather than our backend because it needs the
 * user's own session: `updateUser` writes to the caller's `auth.users` row, and
 * the service-role key could write to anybody's.
 *
 * The flow is two steps. `updateUser({ phone })` puts the number in
 * `phone_change` and sends a six-digit code; `verifyOtp` with `type:
 * 'phone_change'` promotes it to `phone`. The code expires in 60 seconds.
 */

/**
 * Whether the project has an SMS provider behind it.
 *
 * Without one every attempt errors, so the field renders a disabled
 * explanation instead of a button that cannot work. Set
 * `NEXT_PUBLIC_PHONE_AUTH_ENABLED=true` once Twilio/Vonage — or the dashboard's
 * free Test OTP mapping — is configured.
 */
const PHONE_AUTH_ENABLED = process.env.NEXT_PUBLIC_PHONE_AUTH_ENABLED === 'true';

/** Supabase expires the code after 60 seconds. */
const OTP_WINDOW_SECONDS = 60;

export default function PhoneField({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [stage, setStage] = useState<'idle' | 'sent'>('idle');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const verified = Boolean(user.phone_confirmed_at);

  useEffect(() => {
    if (secondsLeft <= 0) return;
    const timer = setTimeout(() => setSecondsLeft((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [secondsLeft]);

  const sendCode = async () => {
    const normalised = normalisePhone(phone);
    if (!isValidPhone(normalised)) {
      setError('Enter the number in international form, e.g. +905551112233.');
      return;
    }

    setBusy(true);
    setError('');
    try {
      const { error: sendError } = await getSupabase().auth.updateUser({ phone: normalised });
      if (sendError) throw sendError;
      setPhone(normalised);
      setStage('sent');
      setSecondsLeft(OTP_WINDOW_SECONDS);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The code could not be sent.');
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (!isValidOtp(code)) {
      setError('The code is six digits.');
      return;
    }

    setBusy(true);
    setError('');
    try {
      const supabase = getSupabase();
      const { error: verifyError } = await supabase.auth.verifyOtp({
        phone,
        token: code.trim(),
        type: 'phone_change',
      });
      if (verifyError) throw verifyError;

      // Supabase matches the code against `auth.users.phone_change`, which is
      // NOT unique — two accounts with the same abandoned pending number can
      // send the verification to the wrong row. So the session is re-read and
      // the confirmation is checked against *this* user before success is
      // claimed. The backend gate reads `phone_confirmed_at` from the verified
      // JWT either way, so this cannot hand out eligibility Supabase did not
      // grant; what it prevents is the UI reporting a success it did not get.
      const { data } = await supabase.auth.getUser();
      if (data.user?.id !== user.id || !data.user?.phone_confirmed_at) {
        setError('That code did not verify this account. Request a new one.');
        return;
      }

      setStage('idle');
      setCode('');
      // The DM gate depends on this, so its cached verdict is now wrong.
      queryClient.invalidateQueries({ queryKey: queryKeys.socialEligibility });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The code could not be verified.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <ProfileCard title="Phone" icon={Phone}>
      {verified ? (
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-up" />
          <div className="min-w-0">
            <p className="text-base text-fg">{user.phone || 'Verified'}</p>
            <p className="text-sm text-fg-subtle">
              Verified. This is one of the requirements for sending direct messages.
            </p>
          </div>
        </div>
      ) : !PHONE_AUTH_ENABLED ? (
        <div>
          <p className="text-base text-fg-muted">Phone verification is not switched on yet.</p>
          <p className="mt-1 text-sm text-fg-subtle">
            It needs an SMS provider configured on the Supabase project. Until then, direct messages
            do not ask for a phone number.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-fg-subtle">
            A verified number is one of the requirements for sending direct messages. We only use it
            to confirm you are a person.
          </p>

          {stage === 'idle' ? (
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1">
                <label htmlFor="phone-number" className="mb-1 block text-sm text-fg-muted">
                  Phone number
                </label>
                <input
                  id="phone-number"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  placeholder="+90 555 111 22 33"
                  className={INPUT_CLASS}
                />
              </div>
              <button
                type="button"
                onClick={() => void sendCode()}
                disabled={busy}
                className="flex h-[2.125rem] shrink-0 items-center gap-1.5 rounded-md bg-accent px-3 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Send code
              </button>
            </div>
          ) : (
            <div className="flex items-end gap-2">
              <div className="min-w-0 flex-1">
                <label htmlFor="phone-otp" className="mb-1 block text-sm text-fg-muted">
                  Code sent to {phone}
                </label>
                <input
                  id="phone-otp"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
                  placeholder="123456"
                  className={`${INPUT_CLASS} font-mono tracking-widest`}
                />
              </div>
              <button
                type="button"
                onClick={() => void verify()}
                disabled={busy}
                className="flex h-[2.125rem] shrink-0 items-center gap-1.5 rounded-md bg-accent px-3 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Verify
              </button>
            </div>
          )}

          {stage === 'sent' && (
            <div className="flex items-center gap-3 text-sm text-fg-subtle">
              {secondsLeft > 0 ? (
                <span>The code expires in {secondsLeft}s.</span>
              ) : (
                <span>That code has expired.</span>
              )}
              <button
                type="button"
                onClick={() => {
                  setStage('idle');
                  setCode('');
                  setError('');
                }}
                className="text-accent transition-opacity hover:underline"
              >
                Use a different number
              </button>
            </div>
          )}

          {error && <p className="text-sm text-down">{error}</p>}
        </div>
      )}
    </ProfileCard>
  );
}
