import type { Page, Route } from '@playwright/test';

/**
 * Network stubs for the browser tests.
 *
 * Every upstream the shell talks to is answered here, inside the browser, so a
 * test never depends on a backend, a Supabase project or a market being open.
 * The payloads are minimal and deterministic: a spec asserts on counts and
 * labels derived from `COINS`, so change that list and the assertions move
 * with it.
 */

/** One row of the overview table, mirroring `CoinData` in `lib/api.ts`. */
interface StubCoin {
  symbol: string;
  name: string;
  change_24h: number;
}

/**
 * Ten assets spread across the histogram's fixed buckets (edges at
 * ±1, ±3, ±6, ±10, ±20). Three land in "+1 / +3", which is the bucket the
 * filter test clicks; the rest exist so that narrowing is visible.
 */
export const COINS: StubCoin[] = [
  { symbol: 'BTCUSDT', name: 'Bitcoin', change_24h: 1.5 },
  { symbol: 'ETHUSDT', name: 'Ethereum', change_24h: 2.0 },
  { symbol: 'SOLUSDT', name: 'Solana', change_24h: 2.9 },
  { symbol: 'BNBUSDT', name: 'BNB', change_24h: -1.5 },
  { symbol: 'XRPUSDT', name: 'XRP', change_24h: -2.5 },
  { symbol: 'ADAUSDT', name: 'Cardano', change_24h: 4.2 },
  { symbol: 'DOGEUSDT', name: 'Dogecoin', change_24h: -25 },
  { symbol: 'AVAXUSDT', name: 'Avalanche', change_24h: 35 },
  { symbol: 'LINKUSDT', name: 'Chainlink', change_24h: 0.4 },
  { symbol: 'DOTUSDT', name: 'Polkadot', change_24h: -0.5 },
];

export const FILTER_BUCKET_LABEL = '+1 / +3';
export const COINS_IN_FILTER_BUCKET = COINS.filter(
  (c) => c.change_24h >= 1 && c.change_24h < 3
).length;

const NOW = '2026-09-04T12:00:00Z';

function marketOverviewPayload() {
  const fear_greed = { value: 55, classification: 'Neutral', timestamp: NOW, history: [] };
  return {
    coins: COINS.map((coin, index) => ({
      ...coin,
      logo: '',
      price: 100 + index,
      change_7d: coin.change_24h / 2,
      sparkline: [1, 2, 3, 2, 3],
      volume_24h: 1_000_000_000,
      high_24h: 110 + index,
      low_24h: 90 + index,
      market_cap: 1_000_000_000_000 / (index + 1),
      market_cap_rank: index + 1,
    })),
    total_volume_24h: 10_000_000_000,
    total_market_cap: 3_000_000_000_000,
    btc_dominance: 55,
    eth_dominance: 15,
    usdt_dominance: 5,
    active_cryptocurrencies: COINS.length,
    fear_greed,
    timestamp: NOW,
  };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

/**
 * Answer the backend the way a warm instance would.
 *
 * Order matters: Playwright consults routes newest-first, so the catch-all is
 * registered before the specific handlers. The catch-all answers 404 rather
 * than 200-with-nothing because the app is written to survive a missing
 * upstream — every panel has an error state — but not a well-formed lie.
 */
export async function stubBackend(page: Page): Promise<void> {
  await page.route('**/api/**', (route) => json(route, { detail: 'not stubbed in e2e' }, 404));

  await page.route('**/api/system/readiness', (route) =>
    json(route, {
      ready: true,
      degraded: false,
      blocked: false,
      elapsed_ms: 1200,
      deadline_ms: 60_000,
      steps: [],
    })
  );

  await page.route('**/api/system/health', (route) =>
    json(route, { status: 'ok', categories: [], checked_at: NOW })
  );

  await page.route('**/api/market-overview', (route) => json(route, marketOverviewPayload()));

  await page.route('**/api/fear-greed', (route) =>
    json(route, { value: 55, classification: 'Neutral', timestamp: NOW, history: [] })
  );
}

/** The shape of the account Supabase would hand back on a successful sign-in. */
export const TEST_USER = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'reader@example.com',
  password: 'correct-horse-battery',
};

/**
 * Stand in for Supabase's GoTrue password grant.
 *
 * `supabase-js` posts to `/auth/v1/token?grant_type=password` and, on a 200,
 * stores the session in localStorage and fires `SIGNED_IN` — which is the
 * event `AuthContext` listens for. Nothing else in the sign-in path leaves
 * the browser, so this one route is the whole of "auth" from the client's
 * point of view. The failure body uses GoTrue's current error format; the
 * client maps it to the "Invalid login credentials" message that
 * `friendlyAuthError` rewrites.
 */
export async function stubSupabaseAuth(page: Page): Promise<void> {
  // Registered first so the password grant below wins: token refresh and
  // `getUser()` never fire in these flows, but a stray call must not reach the
  // network, because the URL in `.env.local` may be a real project.
  await page.route(
    (url) => url.pathname.includes('/auth/v1/'),
    (route) => json(route, { code: 404, msg: 'not stubbed in e2e' }, 404)
  );

  await page.route(
    (url) => url.pathname.endsWith('/auth/v1/token'),
    async (route) => {
      const request = route.request();
      const body = request.postDataJSON() as { email?: string; password?: string } | null;
      const ok = body?.email === TEST_USER.email && body?.password === TEST_USER.password;

      if (!ok) {
        return json(
          route,
          { code: 400, error_code: 'invalid_credentials', msg: 'Invalid login credentials' },
          400
        );
      }

      const issued = Math.floor(Date.now() / 1000);
      const user = {
        id: TEST_USER.id,
        aud: 'authenticated',
        role: 'authenticated',
        email: TEST_USER.email,
        email_confirmed_at: NOW,
        app_metadata: { provider: 'email', providers: ['email'] },
        user_metadata: { full_name: 'E2E Reader' },
        identities: [],
        created_at: NOW,
        updated_at: NOW,
      };
      return json(route, {
        access_token: 'e2e-access-token',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: issued + 3600,
        refresh_token: 'e2e-refresh-token',
        user,
      });
    }
  );
}
