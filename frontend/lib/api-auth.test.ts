import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

const signOut = vi.fn(async () => ({ error: null }));
const getSession = vi.fn(async () => ({ data: { session: { access_token: 'jwt' } } }));

vi.mock('@/lib/supabase', () => ({
  getSupabase: () => ({ auth: { getSession, signOut } }),
}));

import { apiFetch, ApiError } from './api';

function reply(status: number, body: unknown = { detail: 'Not authenticated' }) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

describe('apiFetch on a rejected token', () => {
  beforeEach(() => {
    signOut.mockClear();
    getSession.mockClear();
    // `getAccessToken` returns undefined server-side; the browser branch is
    // what carries the token, so the test has to look like one.
    vi.stubGlobal('window', {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('clears the stored session so gated queries stop firing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => reply(401))
    );

    await expect(apiFetch('/api/admin/me')).rejects.toBeInstanceOf(ApiError);

    expect(signOut).toHaveBeenCalledWith({ scope: 'local' });
  });

  it('leaves the session alone when no token was attached', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => reply(401))
    );

    await expect(apiFetch('/api/price', { anonymous: true })).rejects.toBeInstanceOf(ApiError);

    expect(signOut).not.toHaveBeenCalled();
  });

  it('leaves the session alone on any other failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => reply(403, { detail: 'Admin only' }))
    );

    await expect(apiFetch('/api/admin/me')).rejects.toBeInstanceOf(ApiError);

    expect(signOut).not.toHaveBeenCalled();
  });
});
