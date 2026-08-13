/**
 * The three-pass pipeline, as a diagram.
 *
 * Geometry and copy only — no drawing and no React — so the layout can be
 * reasoned about and changed without opening the canvas code, and so these
 * numbers are the single place the shape lives.
 *
 * Everything is in a 140 x 80 design space, scaled to the canvas at draw time.
 * Wide rather than tall because the pipeline is a sequence: stacked vertically
 * the three steps read as a list, and a list does not have a direction.
 */

export const PASS_VIEW = { width: 140, height: 80 } as const;

export interface PassBox {
  readonly key: 'evidence' | 'draft' | 'review';
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly title: string;
  /** Second line, under the title. The draft's changes once review has run. */
  readonly detail: string;
  /** Body rows. Named rather than counted — "4 sources" is a claim, these are
   *  the sources, and the whole stage is about the difference. */
  readonly lines: readonly string[];
}

/**
 * Stepped down and to the right. A row would leave the return arrow nowhere to
 * go, and a column would make it a straight line back up the same axis, which
 * reads as an undo rather than as an objection.
 */
export const PASS_BOXES: readonly PassBox[] = [
  {
    key: 'evidence',
    x: 1,
    y: 3,
    width: 46,
    height: 36,
    title: 'EVIDENCE',
    detail: 'gathered first',
    lines: [
      'ohlcv · 4h · 148 bars',
      'funding · OI · 36 rows',
      'filings · 13F · 9 rows',
      'news · 14 attributed',
    ],
  },
  {
    key: 'draft',
    x: 56,
    y: 13,
    width: 38,
    height: 24,
    title: 'DRAFT',
    detail: 'v1',
    lines: ['every claim linked'],
  },
  {
    key: 'review',
    x: 92,
    y: 44,
    width: 47,
    height: 30,
    title: 'REVIEW',
    detail: 'argues against it',
    lines: ['1 claim unsupported', '1 risk not stated'],
  },
];

/** What the draft's second line becomes once the review has been applied. */
export const DRAFT_REVISED = 'v2 · reviewed';

/** The line under the diagram. Numbers, not adjectives. */
export const PASS_SUMMARY = '3 passes · 1 rewrite · 0 uncited claims';

export interface Point {
  readonly x: number;
  readonly y: number;
}

const [EVIDENCE, DRAFT, REVIEW] = PASS_BOXES;

const midY = (box: PassBox): number => box.y + box.height / 2;
const midX = (box: PassBox): number => box.x + box.width / 2;

/** Evidence into the draft. */
export const FLOW_IN: readonly Point[] = [
  { x: EVIDENCE.x + EVIDENCE.width, y: midY(EVIDENCE) },
  { x: EVIDENCE.x + EVIDENCE.width + 5, y: midY(EVIDENCE) },
  { x: EVIDENCE.x + EVIDENCE.width + 5, y: midY(DRAFT) },
  { x: DRAFT.x, y: midY(DRAFT) },
];

/** Draft down into the review. */
export const FLOW_OUT: readonly Point[] = [
  { x: midX(DRAFT), y: DRAFT.y + DRAFT.height },
  { x: midX(DRAFT), y: midY(REVIEW) },
  { x: REVIEW.x, y: midY(REVIEW) },
];

/**
 * The review's objection, going back into the draft.
 *
 * Routed over the top, through the empty band above the draft, because that is
 * the only path that crosses neither forward arrow. A feedback line that cuts
 * through the flow it feeds back into reads as a knot.
 */
export const FLOW_BACK: readonly Point[] = [
  { x: midX(REVIEW), y: REVIEW.y },
  { x: midX(REVIEW), y: 6 },
  { x: midX(DRAFT) + 8, y: 6 },
  { x: midX(DRAFT) + 8, y: DRAFT.y },
];

/**
 * Short words hung on the arrows, so each one says what it carries.
 *
 * The evidence-to-draft arrow has none. The gap between those two boxes is nine
 * units wide and the word that belonged there was "cited", which the evidence
 * box's own rows and the summary line below both already say — a label that
 * needs the boxes moved apart to fit is a label the diagram does not need.
 */
export const FLOW_LABELS = {
  out: { text: 'checked', at: { x: midX(DRAFT) + 3, y: midY(REVIEW) - 5 } },
  back: { text: 'rewrite', at: { x: midX(DRAFT) + 12, y: 4 } },
} as const;

export interface PassPhases {
  readonly evidence: number;
  readonly flowIn: number;
  readonly draft: number;
  readonly flowOut: number;
  readonly review: number;
  readonly flowBack: number;
  readonly revised: number;
}

function ramp(progress: number, from: number, span: number): number {
  const t = (progress - from) / span;
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

/**
 * Overlapping windows rather than a strict sequence: each step starts a little
 * before the one before it has finished, so the diagram builds continuously
 * instead of stepping through seven separate stalls.
 */
export function phasesAt(progress: number): PassPhases {
  return {
    evidence: ramp(progress, 0, 0.2),
    flowIn: ramp(progress, 0.16, 0.16),
    draft: ramp(progress, 0.3, 0.16),
    flowOut: ramp(progress, 0.44, 0.16),
    review: ramp(progress, 0.56, 0.16),
    flowBack: ramp(progress, 0.7, 0.18),
    revised: ramp(progress, 0.86, 0.14),
  };
}
