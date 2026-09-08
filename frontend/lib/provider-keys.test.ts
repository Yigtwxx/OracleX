import { describe, expect, it } from 'vitest';

import { isActionable, providerNotice, type ProviderKey } from './provider-keys';

const ALL: ProviderKey[] = ['evds', 'coinalyze', 'sec'];

describe('providerNotice', () => {
  it('returns nothing when the upstream is present', () => {
    for (const provider of ALL) {
      expect(providerNotice(provider, false)).toBeUndefined();
    }
  });

  it('returns a notice for every provider when it is missing', () => {
    for (const provider of ALL) {
      const notice = providerNotice(provider, true);
      expect(notice?.provider).toBe(provider);
      expect(notice?.title).not.toBe('');
      expect(notice?.body).not.toBe('');
    }
  });

  it('points the user-configurable upstreams at the profile tab', () => {
    for (const provider of ['evds', 'coinalyze'] as ProviderKey[]) {
      expect(providerNotice(provider, true)?.href).toBe('/profile?tab=data');
    }
  });

  it('offers no action for the server-only upstream', () => {
    // The ownership board is rebuilt by a scheduler, so a reader has nothing to
    // set — a button here would lead to a form that cannot help them.
    const notice = providerNotice('sec', true);
    expect(notice?.href).toBe('');
    expect(isActionable(notice!)).toBe(false);
  });

  it('marks the user-configurable upstreams as actionable', () => {
    expect(isActionable(providerNotice('evds', true)!)).toBe(true);
    expect(isActionable(providerNotice('coinalyze', true)!)).toBe(true);
  });

  it('never claims the page is broken', () => {
    // These boards keep working without a key; the copy sells the upgrade
    // rather than reporting a failure.
    for (const provider of ALL) {
      const notice = providerNotice(provider, true)!;
      const text = `${notice.title} ${notice.body}`.toLowerCase();
      expect(text).not.toContain('hata');
      expect(text).not.toContain('çalışmıyor');
    }
  });
});
