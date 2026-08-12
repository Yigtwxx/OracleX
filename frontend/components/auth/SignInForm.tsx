'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import AuthField, { FormNotice } from '@/components/auth/AuthField';
import { useAuth } from '@/contexts/AuthContext';
import { friendlyAuthError, validateEmail, validatePassword } from '@/lib/auth-validation';

interface SignInFormProps {
  email: string;
  onEmailChange: (value: string) => void;
  onForgotPassword: () => void;
  /** Carried over from a sign-up that turned out to be a duplicate address. */
  notice?: string;
}

export default function SignInForm({
  email,
  onEmailChange,
  onForgotPassword,
  notice,
}: SignInFormProps) {
  const { signIn } = useAuth();
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');

    const nextErrors: Record<string, string> = {};
    const emailError = validateEmail(email);
    const passwordError = validatePassword(password);
    if (emailError) nextErrors.email = emailError;
    if (passwordError) nextErrors.password = passwordError;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setIsSubmitting(true);
    try {
      const { error } = await signIn(email.trim(), password);
      if (error) setFormError(friendlyAuthError(error));
      // On success there is nothing to do: `onAuthStateChange` swaps the whole
      // page out from under this form.
    } catch (err) {
      setFormError(friendlyAuthError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="space-y-3" onSubmit={handleSubmit} noValidate>
      {notice && !formError && <FormNotice tone="warn">{notice}</FormNotice>}

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
        autoComplete="current-password"
        placeholder="••••••••"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        error={errors.password}
        action={
          <button
            type="button"
            onClick={onForgotPassword}
            className="text-xs text-fg-muted transition-colors hover:text-fg"
          >
            Forgot password?
          </button>
        }
      />

      {formError && <FormNotice tone="error">{formError}</FormNotice>}

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        Sign in
      </button>
    </form>
  );
}
