'use client';

import { useState } from 'react';

import ForgotPasswordForm from '@/components/auth/ForgotPasswordForm';
import SignInForm from '@/components/auth/SignInForm';
import SignUpForm from '@/components/auth/SignUpForm';

export type AuthMode = 'signin' | 'signup' | 'forgot';

type Mode = AuthMode;

interface AuthCardProps {
  /** Which tab opens first. The user can still switch once inside. */
  initialMode?: Mode;
  /**
   * `modal` drops the lead paragraph and the outer card chrome, because the
   * dialog around it already supplies both. Defaults to `page` so the three
   * existing call sites render exactly as before.
   */
  variant?: 'page' | 'modal';
}

const TITLES: Record<Mode, string> = {
  signin: 'Sign in',
  signup: 'Create account',
  forgot: 'Reset password',
};

/**
 * The signed-out half of the profile page.
 *
 * One card, one column. The page used to put a two-column grid here, so a
 * visitor with no account was shown a "Connected Accounts" panel with three
 * disabled buttons next to the form they were meant to be filling in.
 *
 * The email lives here rather than in each form so switching tabs — including
 * the automatic switch when a sign-up hits an address that is already taken —
 * carries the address across instead of making the user type it twice.
 */
export default function AuthCard({ initialMode = 'signin', variant = 'page' }: AuthCardProps = {}) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState('');
  const [notice, setNotice] = useState('');

  const switchTo = (next: Mode) => {
    setMode(next);
    setNotice('');
  };

  return (
    <div className="mx-auto w-full max-w-sm space-y-3">
      {variant === 'page' && (
        <p className="text-center text-base text-fg-muted">
          Sign in to sync your watchlist, notes and chat history across devices.
        </p>
      )}

      <section className={variant === 'page' ? 'surface overflow-hidden' : 'overflow-hidden'}>
        <header className="border-b border-line px-4 py-3">
          {mode === 'forgot' ? (
            <h2 className="text-md font-semibold text-fg">{TITLES.forgot}</h2>
          ) : (
            <div
              role="group"
              aria-label="Account access"
              className="flex rounded-md bg-surface-2 p-0.5"
            >
              {(['signin', 'signup'] as const).map((key) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={mode === key}
                  onClick={() => switchTo(key)}
                  className={`flex-1 rounded px-3 py-1 text-base transition-colors ${
                    mode === key ? 'bg-surface text-fg' : 'text-fg-muted hover:text-fg'
                  }`}
                >
                  {TITLES[key]}
                </button>
              ))}
            </div>
          )}
        </header>

        <div className="p-4">
          {mode === 'signin' && (
            <SignInForm
              email={email}
              onEmailChange={setEmail}
              onForgotPassword={() => setMode('forgot')}
              notice={notice}
            />
          )}
          {mode === 'signup' && (
            <SignUpForm
              email={email}
              onEmailChange={setEmail}
              onAlreadyRegistered={(message) => {
                setMode('signin');
                setNotice(message);
              }}
            />
          )}
          {mode === 'forgot' && (
            <ForgotPasswordForm
              email={email}
              onEmailChange={setEmail}
              onBack={() => switchTo('signin')}
            />
          )}
        </div>
      </section>
    </div>
  );
}
