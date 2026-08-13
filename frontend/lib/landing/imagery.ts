import type { StageKey } from './stages';

/**
 * The picture that sits on the empty half of a stage.
 *
 * One per stage rather than a general asset list: the pairing is the point.
 * Each stage argues for one part of the terminal, and the picture is the thing
 * that part is about — a phone running a chatbot beside the chat panel, the
 * Charging Bull beside the one about the market itself.
 *
 * All present tense. An earlier set was period photography and read as a museum
 * wall next to a chart that is meant to be moving right now.
 *
 * `.landing-figure` in globals.css frames them and drops them to partial
 * opacity, so the tape keeps running through the picture rather than stopping
 * behind it.
 */
export interface StageFigure {
  readonly src: string;
  /** Intrinsic size, only ever used to give the box its aspect ratio. */
  readonly width: number;
  readonly height: number;
}

/**
 * Sizes are the processed files' own, not the originals'. They must be kept in
 * step with `scripts/fetch_landing_imagery.sh`, which is what writes the files
 * and caps them at 720x1000 — swap a picture there and the numbers here move
 * with it. `frontend/public/landing/CREDITS.md` carries the sources.
 *
 * `hero` and `tail` are deliberately absent: the first screen already has the
 * board on it and the last is the page getting out of the way.
 */
const FIGURES: Partial<Record<StageKey, StageFigure>> = {
  print: { src: '/landing/print.jpg', width: 600, height: 900 },
  ai: { src: '/landing/ai.jpg', width: 600, height: 900 },
  chat: { src: '/landing/chat.jpg', width: 663, height: 1000 },
  live: { src: '/landing/live.jpg', width: 600, height: 900 },
  // Source-limited: the press photo is only 580px tall, so its 2:3 crop is
  // narrower than the rest. The frame still matches; only the file is smaller.
  heatmap: { src: '/landing/heatmap.jpg', width: 386, height: 580 },
  macro: { src: '/landing/macro.jpg', width: 600, height: 900 },
  // The two people keep their own shape. Cropping a portrait of someone to 2:3
  // puts the frame through the face, and a column with one landscape in it
  // reads as a considered exception rather than as an oversight.
  ownership: { src: '/landing/ownership.jpg', width: 720, height: 612 },
  social: { src: '/landing/social.jpg', width: 720, height: 900 },
};

export function figureOf(key: StageKey): StageFigure | undefined {
  return FIGURES[key];
}
