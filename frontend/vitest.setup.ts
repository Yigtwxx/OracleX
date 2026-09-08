/**
 * Setup for the jsdom project.
 *
 * The `/vitest` entry point is what registers jest-dom's matchers with vitest's
 * `expect` *and* their types with `tsc` — importing the bare package registers
 * neither, and `toBeInTheDocument` then fails the typecheck rather than the run.
 *
 * `cleanup` is wired explicitly because Testing Library only installs its own
 * afterEach hook when `globals: true`, and every test here imports from
 * 'vitest' by name. Without it a component stays mounted into the next test and
 * `getByText` finds two of everything.
 */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(cleanup);
