import { describe, it, expect } from 'vitest';

import {
  MIN_PASSWORD_LENGTH,
  friendlyAuthError,
  validateEmail,
  validateFullName,
  validatePassword,
  validatePasswordConfirm,
} from './auth-validation';

describe('validateEmail', () => {
  it.each(['user@example.com', 'first.last@sub.example.co.uk', 'user+tag@example.org'])(
    'accepts %s',
    (address) => {
      expect(validateEmail(address)).toBeUndefined();
    }
  );

  it('ignores surrounding whitespace', () => {
    expect(validateEmail('  user@example.com  ')).toBeUndefined();
  });

  it.each(['', '   ', 'nonsense', '@example.com', 'user@', 'user@example', 'a b@example.com'])(
    'refuses %s',
    (address) => {
      expect(validateEmail(address)).toBeTruthy();
    }
  );

  it('asks for an address when the field is empty rather than calling it malformed', () => {
    expect(validateEmail('')).toBe('Enter your email address.');
  });
});

describe('validatePassword', () => {
  it('accepts a password at the minimum length', () => {
    expect(validatePassword('a'.repeat(MIN_PASSWORD_LENGTH))).toBeUndefined();
  });

  it('refuses a password one character short', () => {
    expect(validatePassword('a'.repeat(MIN_PASSWORD_LENGTH - 1))).toBeTruthy();
  });

  it('imposes no composition rules', () => {
    // Length is the whole rule. A lowercase-only password must pass, or the
    // "no uppercase/number requirement" decision has quietly been reversed.
    expect(validatePassword('abcdefgh')).toBeUndefined();
    expect(validatePassword('12345678')).toBeUndefined();
  });
});

describe('validatePasswordConfirm', () => {
  it('accepts a matching confirmation', () => {
    expect(validatePasswordConfirm('secret123', 'secret123')).toBeUndefined();
  });

  it('refuses a mismatch', () => {
    expect(validatePasswordConfirm('secret123', 'secret124')).toBeTruthy();
  });

  it('refuses an empty confirmation even when the password is empty too', () => {
    expect(validatePasswordConfirm('', '')).toBeTruthy();
  });
});

describe('validateFullName', () => {
  it('accepts an ordinary name', () => {
    expect(validateFullName('Ada Lovelace')).toBeUndefined();
  });

  it.each(['', '  ', 'A'])('refuses %s', (name) => {
    expect(validateFullName(name)).toBeTruthy();
  });
});

describe('friendlyAuthError', () => {
  it.each([
    ['Invalid login credentials', 'That email and password do not match.'],
    ['User already registered', 'This email is already registered — sign in instead.'],
    ['Email not confirmed', 'Confirm your email first — check your inbox for the link.'],
  ])('rewrites %s', (raw, expected) => {
    expect(friendlyAuthError(new Error(raw))).toBe(expected);
  });

  it('matches regardless of the provider’s capitalisation', () => {
    expect(friendlyAuthError(new Error('INVALID LOGIN CREDENTIALS'))).toBe(
      'That email and password do not match.'
    );
  });

  it('passes an unrecognised message through rather than replacing it with a shrug', () => {
    expect(friendlyAuthError(new Error('Database offline'))).toBe('Database offline');
  });

  it('handles a non-Error value', () => {
    expect(friendlyAuthError('Invalid login credentials')).toBe(
      'That email and password do not match.'
    );
  });

  it('falls back to a generic sentence when there is no message at all', () => {
    expect(friendlyAuthError(undefined)).toBe('Something went wrong. Try again.');
    expect(friendlyAuthError(new Error(''))).toBe('Something went wrong. Try again.');
  });
});
