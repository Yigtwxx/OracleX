import { mulberry32 } from './prng';
import { StageKey, within } from './stages';

/**
 * The wire between a copy panel and the tape underneath it.
 *
 * A panel that simply fades up is a marketing block that happens to sit over a
 * chart. A panel wired to a bar is a note somebody left on the tape — which is
 * the conceit of the whole page, so the wire is not decoration.
 *
 * Which bar is *not* fixed here. The visible window depends on the viewport and
 * pans as the page scrolls, so a bar chosen offline is under the panel on one
 * screen and off the edge on the next. This carries a stable seed instead, and
 * the renderer resolves it against the window it actually has.
 */
export interface NoteAnchor {
  readonly key: StageKey;
  /** Seeded 0–1. Where along the far side of the plot the wire starts. */
  readonly pick: number;
  /** Which end of the bar the wire attaches to. */
  readonly side: 'high' | 'low';
  readonly from: number;
  readonly to: number;
}

/** Stable 32-bit seed from a stage key, so each panel picks its own bar. */
function seedOf(key: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i += 1) {
    hash ^= key.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/**
 * Seeded rather than random: the page renders on the server too, and a wire
 * that moved between render and hydration would be a visible jump.
 */
function anchorFor(key: StageKey): NoteAnchor {
  const random = mulberry32(seedOf(key));
  // The wire is drawn early in the stage, while the panel is arriving, and is
  // finished well before the stage's own annotation appears.
  const slot = within(key, 0.12, 0.42);

  return {
    key,
    pick: random(),
    side: random() < 0.5 ? 'high' : 'low',
    from: slot.from,
    to: slot.to,
  };
}

/** Every stage that carries a copy panel, in page order. */
const NOTE_STAGES: readonly StageKey[] = [
  'print',
  'ai',
  'chat',
  'live',
  'heatmap',
  'macro',
  'ownership',
  'social',
];

export const NOTE_ANCHORS: readonly NoteAnchor[] = NOTE_STAGES.map(anchorFor);

export function anchorOf(key: StageKey): NoteAnchor | undefined {
  return NOTE_ANCHORS.find((a) => a.key === key);
}
