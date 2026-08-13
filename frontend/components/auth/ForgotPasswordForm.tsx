'use client';

import { useState } from 'react';
import { ArrowLeft, Loader2 } from 'lucide-react';

import AuthField, { FormNotice } from '@/components/auth/AuthField';
import { useAuth } from '@/contexts/AuthContext';
import { friendlyAuthError, validateEmail } from '@/lib/auth-validation';

interface ForgotPasswordFormProps {
  email: string;
  onEmailChange: (value: string) => void;
  onBack: () => void;
}

export default function ForgotPasswordForm({
  email,
  onEmailChange,
  onBack,
}: ForgotPasswordFormProps) {
  const { sendPasswordReset } = useAuth();
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [sent, setSent] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError('');

    const emailError = validateEmail(email);
    setError(emailError ?? '');
    if (emailError) return;

    setIsSubmitting(true);
    try {
      const { error: resetError } = await sendPasswordReset(email.trim());
      if (resetError) {
        setFormError(friendlyAuthError(resetError));
        return;
      }
      setSent(true);
    } catch (err) {
      setFormError(friendlyAuthError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (sent) {
    return (
      <div className="space-y-3">
        <FormNotice tone="success">Reset link sent.</FormNotice>
        {/* Deliberately neutral about whether the address has an account. The
            duplicate check on sign-up is a considered exception; there is no
            reason to repeat it here, where saying so buys the user nothing. */}
        <p className="text-base text-fg-muted">
          If <span className="text-fg">{email.trim()}</span> has an account, a link to set a new
          password is on its way. It expires in an hour.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1.5 text-base text-fg-muted transition-colors hover:text-fg"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to sign in
        </button>
      </div>
    );
  }

  return (
    <form className="space-y-3" onSubmit={handleSubmit} noValidate>
      <p className="text-base text-fg-muted">
        Type the address on your account and we will send a link to set a new password.
      </p>

      <AuthField
        label="Email"
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        value={email}
        onChange={(event) => onEmailChange(event.target.value)}
        error={error}
      />

      {formError && <FormNotice tone="error">{formError}</FormNotice>}

      <button
        type="submit"
        disabled={isSubmitting}
        className="flex w-full items-center justify-center gap-2 rounded-md bg-accent px-3 py-1.5 text-base text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-50"
      >
        {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        Send reset link
      </button>

      <button
        type="button"
        onClick={onBack}
        className="flex items-center gap-1.5 text-base text-fg-muted transition-colors hover:text-fg"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to sign in
      </button>
    </form>
  );
}
