'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import AuthField, { FormNotice } from '@/components/auth/AuthField';
import { useAuth } from '@/contexts/AuthContext';
import { ApiError, precheckEmail } from '@/lib/api';
import {
  MIN_PASSWORD_LENGTH,
  friendlyAuthError,
  validateEmail,
  validateFullName,
  validatePassword,
} from '@/lib/auth-validation';

interface SignUpFormProps {
  email: string;
  onEmailChange: (value: string) => void;
  /** Flip the card to Sign in, carrying the address and a reason. */
  onAlreadyRegistered: (message: string) => void;
}

export default function SignUpForm({ email, onEmailChange, onAlreadyRegistered }: SignUpFormProps) {
  const { signUp } = useAuth();
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [sentTo, setSentTo] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');

    const trimmedEmail = email.trim();
    const trimmedName = fullName.trim();

    const nextErrors: Record<string, string> = {};
    const nameError = validateFullName(trimmedName);
    const emailError = validateEmail(trimmedEmail);
    const passwordError = validatePassword(password);
    if (nameError) nextErrors.fullName = nameError;
    if (emailError) nextErrors.email = emailError;
    if (passwordError) nextErrors.password = passwordError;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      // Ask the backend whether this address is worth trying, before Supabase
      // gets involved. It answers three things the browser cannot: is the
      // domain real, is it a throwaway service, and is the address already
      // taken. See routers/auth.py.
      try {
        const verdict = await precheckEmail(trimmedEmail);

        if (verdict.registered) {
          onAlreadyRegistered(verdict.message);
          return;
        }
        if (!verdict.deliverable) {
          setErrors({ email: verdict.message });
          return;
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 429) {
          setFormError(err.message);
          return;
        }
        // Anything else — the backend is down, the network blipped — is not a
        // reason to block a sign-up. The check is a courtesy; Supabase's own
        // duplicate error and its confirmation email are the real gates.
        console.warn('[SignUp] email precheck skipped:', err);
      }

      const { error } = await signUp(trimmedEmail, password, trimmedName);
      if (error) {
        const message = friendlyAuthError(error);
        // Backstop for the precheck: if it was skipped or raced, Supabase still
        // reports the duplicate and the user still lands on the right tab.
        if (message.includes('already registered')) {
          onAlreadyRegistered(message);
          return;
        }
        setFormError(message);
        return;
      }

      setSentTo(trimmedEmail);
    } catch (err) {
      setFormError(friendlyAuthError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (sentTo) {
    return (
      <div className="space-y-3">
        <FormNotice tone="success">Account created. Confirm it from your inbox.</FormNotice>
        <p className="text-base text-fg-muted">
          We sent a confirmation link to <span className="text-fg">{sentTo}</span>. Open it to
          finish signing up — you will not be able to sign in until you do.
        </p>
        <p className="text-sm text-fg-subtle">
          Nothing arrived? Check the spam folder, then try signing in — you can resend the link from
          there.
        </p>
      </div>
    );
  }

  return (
    <form className="space-y-3" onSubmit={handleSubmit} noValidate>
      <AuthField
        label="Full name"
        type="text"
        autoComplete="name"
        placeholder="Ada Lovelace"
        value={fullName}
        onChange={(event) => setFullName(event.target.value)}
        error={errors.fullName}
      />

      <AuthField
        label="Email"
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        value={email}
        onChange={(event) => onEmailChange(event.target.value)}
        error={errors.email}
      />

      <AuthField
        label="Password"
        type="password"
        autoComplete="new-password"
        placeholder="••••••••"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        error={errors.password}
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
      />

      {formError && <FormNotice tone="error">{formError}</FormNotice>}

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-1.5 text-base text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        Create account
      </button>
    </form>
  );
}
