/**
 * Field checks and error wording for the auth forms.
 *
 * Pure functions with no React and no network, so the rules can be tested
 * directly. They live in `lib/` because that is what `vitest.config.mts`
 * collects.
 *
 * Deliberately *not* a schema library. Three short forms with a
 * `Record<string, string>` of messages do not earn zod plus react-hook-form in
 * a project that justifies every dependency it has.
 *
 * The password rule is length only — no uppercase/digit/symbol requirement.
 * That is a decision, not an oversight: composition rules push people towards
 * `Password1!` and were dropped from the NIST guidance years ago. Length is the
 * part that matters, and Supabase enforces its own project minimum behind this.
 */

/** Matches the Supabase project default. */
export const MIN_PASSWORD_LENGTH = 6;

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** `undefined` means valid — so a caller can build an error map by assignment. */
export function validateEmail(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return 'Enter your email address.';
  if (!EMAIL_SHAPE.test(trimmed)) return 'That does not look like an email address.';
  return undefined;
}

export function validatePassword(value: string): string | undefined {
  if (!value) return 'Enter a password.';
  if (value.length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  return undefined;
}

export function validatePasswordConfirm(password: string, confirm: string): string | undefined {
  if (!confirm) return 'Type the password again.';
  if (password !== confirm) return 'The two passwords do not match.';
  return undefined;
}

export function validateFullName(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return 'Enter your name.';
  if (trimmed.length < 2) return 'That name is too short.';
  return undefined;
}

/**
 * GoTrue's raw message, rewritten in the app's voice.
 *
 * These strings used to be rendered verbatim. "Invalid login credentials" is
 * accurate and tells the reader nothing about what to do next; worse, an
 * unmapped provider string is the kind of text that leaks implementation
 * detail into a screenshot.
 */
export function friendlyAuthError(error: unknown): string {
  const raw = error instanceof Error ? error.message : typeof error === 'string' ? error : '';
  const message = raw.toLowerCase();

  if (!message) return 'Something went wrong. Try again.';

  if (message.includes('invalid login credentials')) {
    return 'That email and password do not match.';
  }
  if (message.includes('user already registered') || message.includes('already been registered')) {
    return 'This email is already registered — sign in instead.';
  }
  if (message.includes('email not confirmed')) {
    return 'Confirm your email first — check your inbox for the link.';
  }
  if (
    message.includes('password should be at least') ||
    message.includes('password is too short')
  ) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (message.includes('same as the old password') || message.includes('should be different')) {
    return 'That is already your password. Choose a different one.';
  }
  if (message.includes('for security purposes') || message.includes('rate limit')) {
    return 'Too many attempts. Wait a minute and try again.';
  }
  if (message.includes('email address') && message.includes('invalid')) {
    return 'That address was refused. Check the spelling.';
  }
  if (message.includes('failed to fetch') || message.includes('networkerror')) {
    return 'Could not reach the server. Check your connection.';
  }
  if (message.includes('auth session missing') || message.includes('session_not_found')) {
    return 'Your session has expired. Sign in again.';
  }

  // Nothing matched. Show the provider's own sentence rather than a shrug —
  // it is still more useful to the reader than "an error occurred".
  return raw;
}
