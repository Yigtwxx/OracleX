/**
 * The provider fallback chain, as a diagram.
 *
 * Geometry and copy only — no drawing and no React — for the same reason
 * `passes.ts` is split this way: the shape is worth being able to change
 * without opening the canvas code.
 *
 * Tall rather than wide, which is the opposite of the pass diagram and is the
 * point. A pipeline moves forward; a fallback chain moves *down*, one rung at a
 * time, and the reader should be able to see that the request is descending
 * rather than progressing. It also has to fit a three-hundred-pixel rail.
 */

import { ramp } from './ramp';

export const CHAIN_VIEW = { width: 100, height: 124 } as const;

export interface ChainBox {
  readonly key: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly title: string;
  /** Second line, in the subtle tone. Omitted where the title says it all. */
  readonly detail?: string;
  /** Dashed outline rather than solid: present only when the caller asked. */
  readonly optional?: boolean;
  /** How this rung ends. Drives the tone the box is drawn in. */
  readonly outcome?: 'declined' | 'answered';
}

/**
 * The rungs, and the two boxes that bracket them.
 *
 * Three providers because two would not show the difference between "the
 * fallback ran" and "the chain kept going". The first two decline for different
 * reasons on purpose — a chain that only ever fails one way looks like a retry.
 */
export const CHAIN_BOXES: readonly ChainBox[] = [
  {
    key: 'request',
    x: 0,
    y: 0,
    width: 44,
    height: 13,
    title: 'REQUEST',
  },
  {
    key: 'prefer',
    x: 52,
    y: 0,
    width: 48,
    height: 13,
    title: 'prefer',
    detail: 'prepended',
    optional: true,
  },
  {
    key: 'local',
    x: 0,
    y: 26,
    width: 62,
    height: 17,
    title: 'ollama',
    detail: 'local · no key',
    outcome: 'declined',
  },
  {
    key: 'hosted',
    x: 0,
    y: 55,
    width: 62,
    height: 17,
    title: 'groq',
    detail: 'rate limited',
    outcome: 'declined',
  },
  {
    key: 'answered',
    x: 0,
    y: 84,
    width: 62,
    height: 17,
    title: 'anthropic',
    detail: 'answers',
    outcome: 'answered',
  },
  {
    key: 'reply',
    x: 0,
    y: 111,
    width: 62,
    height: 13,
    title: 'REPLY',
  },
];

/**
 * The cooldown stamps, hung off the rungs that declined.
 *
 * To the right of the ladder rather than on it, because a cooldown is not a
 * step the request takes — it is something left behind on the provider, and it
 * applies to the *next* call rather than this one. Drawing it inline would say
 * the request waited, which is the one thing the chain never does.
 */
export interface ChainStamp {
  readonly forKey: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly text: string;
}

export const CHAIN_STAMPS: readonly ChainStamp[] = [
  { forKey: 'local', x: 70, y: 29, width: 30, height: 11, text: 'skipped' },
  { forKey: 'hosted', x: 70, y: 58, width: 30, height: 11, text: 'cooldown' },
];

export interface Point {
  readonly x: number;
  readonly y: number;
}

const box = (key: string): ChainBox => {
  const found = CHAIN_BOXES.find((b) => b.key === key);
  if (!found) throw new Error(`Unknown chain box: ${key}`);
  return found;
};

const below = (key: string): Point => {
  const b = box(key);
  return { x: b.x + b.width / 2, y: b.y + b.height };
};

const above = (key: string): Point => {
  const b = box(key);
  return { x: b.x + b.width / 2, y: b.y };
};

/** The descent. One segment per rung, each drawn as its own phase. */
export const CHAIN_FLOWS: readonly (readonly Point[])[] = [
  [below('request'), above('local')],
  [below('local'), above('hosted')],
  [below('hosted'), above('answered')],
  [below('answered'), above('reply')],
];

/** The line under the diagram. Counts, not adjectives. */
export const CHAIN_SUMMARY = 'rebuilt per call · never cached';

export interface ChainPhases {
  readonly request: number;
  readonly prefer: number;
  readonly toLocal: number;
  readonly local: number;
  readonly toHosted: number;
  readonly hosted: number;
  readonly toAnswered: number;
  readonly answered: number;
  readonly toReply: number;
  readonly reply: number;
}

/**
 * Overlapping windows rather than a strict sequence, so the ladder builds
 * continuously instead of stepping through ten separate stalls. The windows are
 * ordered and the last one closes at one, which `chain.test.ts` asserts.
 */
export function phasesAt(progress: number): ChainPhases {
  return {
    request: ramp(progress, 0, 0.12),
    prefer: ramp(progress, 0.06, 0.12),
    toLocal: ramp(progress, 0.14, 0.1),
    local: ramp(progress, 0.2, 0.12),
    toHosted: ramp(progress, 0.32, 0.1),
    hosted: ramp(progress, 0.38, 0.12),
    toAnswered: ramp(progress, 0.5, 0.1),
    answered: ramp(progress, 0.56, 0.14),
    toReply: ramp(progress, 0.72, 0.12),
    reply: ramp(progress, 0.82, 0.18),
  };
}
