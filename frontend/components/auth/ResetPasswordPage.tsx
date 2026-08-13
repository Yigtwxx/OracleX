'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { KeyRound, Loader2 } from 'lucide-react';

import AuthField, { FormNotice } from '@/components/auth/AuthField';
import { useAuth } from '@/contexts/AuthContext';
import { getSupabase } from '@/lib/supabase';
import {
  MIN_PASSWORD_LENGTH,
  friendlyAuthError,
  validatePassword,
  validatePasswordConfirm,
} from '@/lib/auth-validation';

type Stage = 'checking' | 'ready' | 'expired' | 'done';

/**
 * The screen a password-reset email lands on.
 *
 * `getSupabase()` builds the client with `detectSessionInUrl` on and the
 * implicit flow, so the usual link — `#access_token=…&type=recovery` — is
 * consumed the moment the client is constructed and simply shows up as a
 * session. The two other branches below are the ones worth writing down:
 *
 *   * An expired or already-used link comes back as `#error_description=…` and
 *     never produces a session. Without this branch the page sits on a form
 *     that cannot work and says nothing about why.
 *   * A project switched to the PKCE flow sends `?code=…` instead, which has to
 *     be exchanged by hand.
 */
export default function ResetPasswordPage() {
  const router = useRouter();
  const { updatePassword } = useAuth();
  const [stage, setStage] = useState<Stage>('checking');
  const [linkError, setLinkError] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const resolve = async () => {
      const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const description = hash.get('error_description');
      if (description) {
        if (!cancelled) {
          setLinkError(description.replace(/\+/g, ' '));
          setStage('expired');
        }
        return;
      }

      const supabase = getSupabase();
      const code = new URLSearchParams(window.location.search).get('code');
      if (code) {
        const { error } = await supabase.auth.exchangeCodeForSession(code);
        if (error && !cancelled) {
          setLinkError(friendlyAuthError(error));
          setStage('expired');
          return;
        }
      }

      const { data } = await supabase.auth.getSession();
      if (cancelled) return;
      setStage(data.session ? 'ready' : 'expired');
    };

    resolve();

    // The hash may still be in flight when this mounts; a PASSWORD_RECOVERY or
    // SIGNED_IN event is the client telling us it has finished reading it.
    const {
      data: { subscription },
    } = getSupabase().auth.onAuthStateChange((_event, session) => {
      if (!cancelled && session) setStage((prev) => (prev === 'done' ? prev : 'ready'));
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');

    const nextErrors: Record<string, string> = {};
    const passwordError = validatePassword(password);
    const confirmError = validatePasswordConfirm(password, confirm);
    if (passwordError) nextErrors.password = passwordError;
    if (confirmError) nextErrors.confirm = confirmError;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      const { error } = await updatePassword(password);
      if (error) {
        setFormError(friendlyAuthError(error));
        return;
      }
      setStage('done');
      // The user just proved control of the mailbox, so the session they were
      // given stays — signing them out here would only make them type the new
      // password immediately.
      setTimeout(() => router.replace('/profile'), 1200);
    } catch (err) {
      setFormError(friendlyAuthError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <section className="surface w-full max-w-sm overflow-hidden">
        <header className="flex items-center gap-2 border-b border-line px-4 py-3">
          <KeyRound className="h-3.5 w-3.5 text-fg-muted" />
          <h1 className="text-md font-semibold text-fg">Set a new password</h1>
        </header>

        <div className="space-y-3 p-4">
          {stage === 'checking' && <div className="shimmer h-24 w-full rounded-md" />}

          {stage === 'expired' && (
            <>
              <FormNotice tone="error">This link has expired or has already been used.</FormNotice>
              {linkError && <p className="text-sm text-fg-subtle">{linkError}</p>}
              <p className="text-base text-fg-muted">
                Reset links are good for one hour and one use. Request a fresh one from the sign-in
                screen.
              </p>
              <button
                type="button"
                onClick={() => router.replace('/profile')}
                className="w-full rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
              >
                Back to sign in
              </button>
            </>
          )}

          {stage === 'done' && (
            <>
              <FormNotice tone="success">Password updated.</FormNotice>
              <p className="text-base text-fg-muted">You are signed in. Taking you to Profile…</p>
            </>
          )}

          {stage === 'ready' && (
            <form className="space-y-3" onSubmit={handleSubmit} noValidate>
              <AuthField
                label="New password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                error={errors.password}
                hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
              />
              <AuthField
                label="Confirm password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                error={errors.confirm}
              />

              {formError && <FormNotice tone="error">{formError}</FormNotice>}

              <button
                type="submit"
                disabled={isSubmitting}
                className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-1.5 text-base text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Update password
              </button>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}
