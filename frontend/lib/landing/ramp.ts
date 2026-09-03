/**
 * The easing every staged figure on this site is built from.
 *
 * Extracted from `passes.ts` when the provider-chain diagram needed the same
 * thing. Both diagrams describe a sequence whose steps overlap, and both express
 * that as a set of windows over one progress value — so the window function
 * belongs to neither of them.
 */

export function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * How far into the window `[from, from + span]` a progress value has come.
 *
 * Returns 0 before the window opens and 1 after it closes, which is what lets a
 * caller state each step's window independently instead of threading the
 * previous step's end into the next step's start.
 */
export function ramp(progress: number, from: number, span: number): number {
  return clamp01((progress - from) / span);
}
