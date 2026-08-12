'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { MailCheck } from 'lucide-react';

import { FormNotice } from '@/components/auth/AuthField';
import { getSupabase } from '@/lib/supabase';
import { friendlyAuthError } from '@/lib/auth-validation';

/**
 * Where a confirmation link comes back to.
 *
 * `emailRedirectTo` in AuthContext has always pointed here; the route simply
 * did not exist, so confirming an account landed on a 404 and looked like the
 * link was broken. All this screen does is wait for the client to finish
 * reading the URL and then hand the user to their profile.
 */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const finish = async () => {
      const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
      const description = hash.get('error_description');
      if (description) {
        if (!cancelled) setError(description.replace(/\+/g, ' '));
        return;
      }

      const supabase = getSupabase();
      const code = new URLSearchParams(window.location.search).get('code');
      if (code) {
        const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
        if (exchangeError && !cancelled) {
          setError(friendlyAuthError(exchangeError));
          return;
        }
      }

      if (!cancelled) router.replace('/profile');
    };

    finish();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="surface w-full max-w-sm px-6 py-10 text-center">
        <MailCheck className="mx-auto mb-3 h-6 w-6 text-fg-subtle" />
        {error ? (
          <div className="space-y-3 text-left">
            <FormNotice tone="error">This link did not work.</FormNotice>
            <p className="text-sm text-fg-subtle">{error}</p>
            <button
              type="button"
              onClick={() => router.replace('/profile')}
              className="w-full rounded-md border border-line px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
            >
              Go to Profile
            </button>
          </div>
        ) : (
          <>
            <h1 className="mb-1.5 text-md font-semibold text-fg">Confirming your account…</h1>
            <p className="text-base text-fg-muted">One moment.</p>
          </>
        )}
      </div>
    </div>
  );
}
