import { defineConfig } from 'vitest/config';

/**
 * Scoped to the pure modules under `lib/`.
 *
 * No jsdom, no @testing-library: the logic worth pinning here is geometry and
 * bucket boundaries, and both are plain functions. Component behaviour —
 * focus order, contrast, keyboard reachability — is verified against a real
 * browser instead, where those claims can actually be measured.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['lib/**/*.test.ts'],
  },
  resolve: {
    alias: { '@': import.meta.dirname },
  },
});
