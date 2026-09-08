import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const alias = { '@': import.meta.dirname };

/**
 * Two suites, split by what each can honestly measure.
 *
 * `unit` runs the pure modules under `lib/` in node: geometry, bucket
 * boundaries, formatting — plain functions that need no DOM at all.
 *
 * `components` runs in jsdom, and its remit is deliberately narrow: *which
 * branch* a component renders. Loading versus error versus empty versus
 * populated are decisions a component makes from its props, they are where the
 * bugs actually were — a failed feed rendering as a quiet market — and jsdom
 * answers them in milliseconds.
 *
 * Everything jsdom would have to approximate stays in Playwright. Focus order,
 * contrast, keyboard reachability and layout are claims about a real engine,
 * and asserting them against a DOM implementation that computes no layout is
 * asserting the stub rather than the browser. The split is the point: neither
 * suite is asked for a verdict it cannot give.
 */
export default defineConfig({
  resolve: { alias },
  test: {
    projects: [
      {
        // Repeated per project on purpose: a project is its own Vite config and
        // does not inherit the root's resolution.
        resolve: { alias },
        test: {
          name: 'unit',
          environment: 'node',
          include: ['lib/**/*.test.ts'],
        },
      },
      {
        // The JSX transform has to be asked for. Vitest's SSR pipeline parses a
        // `.tsx` file with no JSX loader attached and fails on the first tag —
        // `unit` needs none of this, which is why the plugin sits on the one
        // project rather than at the root.
        plugins: [react()],
        resolve: { alias },
        test: {
          name: 'components',
          environment: 'jsdom',
          include: ['components/**/*.test.tsx'],
          setupFiles: ['./vitest.setup.ts'],
        },
      },
    ],
  },
});
