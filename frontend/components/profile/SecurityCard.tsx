'use client';

import { useState } from 'react';
import { Loader2, Lock } from 'lucide-react';

import AuthField, { FormNotice } from '@/components/auth/AuthField';
import ProfileCard from '@/components/profile/ProfileCard';
import { useAuth } from '@/contexts/AuthContext';
import {
  MIN_PASSWORD_LENGTH,
  friendlyAuthError,
  validatePassword,
  validatePasswordConfirm,
} from '@/lib/auth-validation';

/**
 * Change password.
 *
 * The current password is asked for and then actually checked, by signing in
 * with it before the change goes through. Supabase's `updateUser` does not
 * require it — the session alone is enough — which means a borrowed, unlocked
 * browser could otherwise change the password and lock the owner out.
 */
export default function SecurityCard({ email }: { email: string }) {
  const { signIn, updatePassword } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [done, setDone] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');
    setDone(false);

    const nextErrors: Record<string, string> = {};
    if (!current) nextErrors.current = 'Enter your current password.';
    const nextError = validatePassword(next);
    const confirmError = validatePasswordConfirm(next, confirm);
    if (nextError) nextErrors.next = nextError;
    if (confirmError) nextErrors.confirm = confirmError;
    if (current && next && current === next) {
      nextErrors.next = 'That is already your password. Choose a different one.';
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      const { error: signInError } = await signIn(email, current);
      if (signInError) {
        setErrors({ current: 'That is not your current password.' });
        return;
      }

      const { error } = await updatePassword(next);
      if (error) {
        setFormError(friendlyAuthError(error));
        return;
      }

      setDone(true);
      setCurrent('');
      setNext('');
      setConfirm('');
    } catch (err) {
      setFormError(friendlyAuthError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <ProfileCard title="Password" icon={Lock}>
      <form className="max-w-sm space-y-3" onSubmit={handleSubmit} noValidate>
        <AuthField
          label="Current password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
          error={errors.current}
        />
        <AuthField
          label="New password"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          error={errors.next}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        />
        <AuthField
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          placeholder="••••••••"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          error={errors.confirm}
        />

        {formError && <FormNotice tone="error">{formError}</FormNotice>}
        {done && <FormNotice tone="success">Password updated.</FormNotice>}

        <button
          type="submit"
          disabled={isSubmitting}
          className="flex items-center justify-center gap-2 rounded-md bg-accent px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Update password
        </button>
      </form>
    </ProfileCard>
  );
}
