import { defineConfig, devices } from '@playwright/test';

/**
 * Browser tests for the terminal shell.
 *
 * These drive the real Next.js app in a real Chromium, with every upstream —
 * the FastAPI backend and Supabase auth — answered by route stubs inside the
 * browser (see `e2e/stubs.ts`). That is a deliberate boundary, not a
 * shortcut: the backend cannot start without a Supabase project, so a suite
 * that needed it would never run in CI, and the backend's own contract is
 * already pinned by pytest. What has no other guard is the chain in between —
 * router → hook → component → DOM — and that is what these cover.
 *
 * Locally the config reuses a `next dev` already listening on :3100 rather
 * than starting its own; the two share `.next/`, and a second server, or a
 * build, on top of a running one corrupts it.
 */
const PORT = 3100;
const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  reporter: isCI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // CI has already run `next build` by the time this job starts, so serving
    // that output is both faster and closer to what ships than `next dev`.
    command: isCI ? `npm run start` : `npm run dev`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !isCI,
    timeout: 120_000,
  },
});
