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
        //
        // This project is the one thing in the repository with a real Node
        // floor: `jsdom` pulls in undici, which wants 22.19 or newer, and the
        // failure mode is not a failing assertion but every worker here
        // refusing to start with "webidl.util.markAsUncloneable is not a
        // function" — which reads as a broken harness rather than as a version
        // problem, and shows up only in CI because a developer's Node is
        // usually newer. `.github/workflows/ci.yml` and `frontend/Dockerfile`
        // are on 22 for this among other reasons; check a jsdom upgrade's
        // engines against them rather than against `node -v`.
        plugins: [react()],
        resolve: { alias },
        test: {
          name: 'components',
          environment: 'jsdom',
          // `hooks/` joins the jsdom project rather than `unit`: a hook is
          // only observable through a render, and its lifecycle — mount,
          // StrictMode's double mount, unmount — is the part worth asserting.
          include: ['components/**/*.test.tsx', 'hooks/**/*.test.tsx'],
          setupFiles: ['./vitest.setup.ts'],
        },
      },
    ],
  },
});
