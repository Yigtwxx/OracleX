'use client';

import { createContext, useContext, useEffect, useState, ReactNode } from 'react';
import { User, Session, AuthChangeEvent } from '@supabase/supabase-js';
import { getSupabase } from '@/lib/supabase';

type AuthResult = { error: Error | null };

interface AuthContextType {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<AuthResult>;
  /**
   * `fullName` is not decoration. It is written to `raw_user_meta_data`, which
   * is what the `handle_new_user()` trigger copies into `profiles.full_name` —
   * the sign-up form used to collect the name and drop it on the floor, leaving
   * every profile nameless.
   */
  signUp: (email: string, password: string, fullName?: string) => Promise<AuthResult>;
  signOut: () => Promise<void>;
  signInWithGoogle: () => Promise<AuthResult>;
  sendPasswordReset: (email: string) => Promise<AuthResult>;
  updatePassword: (newPassword: string) => Promise<AuthResult>;
  resendConfirmation: (email: string) => Promise<AuthResult>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/** Where Supabase sends the browser back to after an emailed link. */
function redirectTo(path: string): string | undefined {
  if (typeof window === 'undefined') return undefined;
  return `${window.location.origin}${path}`;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = getSupabase();

    // Get initial session
    supabase.auth.getSession().then(({ data: { session: initialSession } }) => {
      setSession(initialSession);
      setUser(initialSession?.user ?? null);
      setLoading(false);
    });

    // Listen for auth changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event: AuthChangeEvent, newSession: Session | null) => {
      setSession(newSession);
      setUser(newSession?.user ?? null);
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const signIn = async (email: string, password: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return { error };
  };

  const signUp = async (email: string, password: string, fullName?: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: fullName ? { full_name: fullName } : undefined,
        emailRedirectTo: redirectTo('/auth/callback'),
      },
    });
    return { error };
  };

  const signOut = async () => {
    const supabase = getSupabase();
    await supabase.auth.signOut();
  };

  const signInWithGoogle = async () => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: redirectTo('/auth/callback') },
    });
    return { error };
  };

  const sendPasswordReset = async (email: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: redirectTo('/auth/reset-password'),
    });
    return { error };
  };

  const updatePassword = async (newPassword: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    return { error };
  };

  const resendConfirmation = async (email: string) => {
    const supabase = getSupabase();
    const { error } = await supabase.auth.resend({
      type: 'signup',
      email,
      options: { emailRedirectTo: redirectTo('/auth/callback') },
    });
    return { error };
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        loading,
        signIn,
        signUp,
        signOut,
        signInWithGoogle,
        sendPasswordReset,
        updatePassword,
        resendConfirmation,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

/**
 * Safe fallback used when a component may render outside an AuthProvider.
 *
 * Every action reports failure rather than success. An earlier version returned
 * `{ error: null }`, so a form mounted outside the provider would announce
 * "signed in" having done nothing at all.
 */
const OUTSIDE_PROVIDER: AuthResult = {
  error: new Error('Authentication is unavailable on this screen.'),
};

const FALLBACK_AUTH: AuthContextType = {
  user: null,
  session: null,
  loading: false,
  signIn: async () => OUTSIDE_PROVIDER,
  signUp: async () => OUTSIDE_PROVIDER,
  signOut: async () => {},
  signInWithGoogle: async () => OUTSIDE_PROVIDER,
  sendPasswordReset: async () => OUTSIDE_PROVIDER,
  updatePassword: async () => OUTSIDE_PROVIDER,
  resendConfirmation: async () => OUTSIDE_PROVIDER,
};

/**
 * Like {@link useAuth} but never throws — returns a safe, unauthenticated
 * default when no AuthProvider is present. The hook is always called
 * unconditionally, satisfying the rules of hooks.
 */
export function useOptionalAuth(): AuthContextType {
  return useContext(AuthContext) ?? FALLBACK_AUTH;
}
