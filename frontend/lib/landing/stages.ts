import { LLM } from '@/lib/generated/repo-facts';

export type StageKey =
  'hero' | 'print' | 'ai' | 'chat' | 'live' | 'heatmap' | 'macro' | 'ownership' | 'social' | 'tail';

export interface Stage {
  readonly key: StageKey;
  /** Section height in viewport heights. The scroll schedule is derived from
   *  these, so changing one moves both the copy and the canvas together. */
  readonly vh: number;
}

export interface StageWindow {
  readonly key: StageKey;
  readonly from: number;
  readonly to: number;
}

/** A number worth stating outright, shown in mono under the panel's copy. */
export interface FeatureMetric {
  readonly value: string;
  readonly label: string;
}

export interface Feature {
  readonly key: StageKey;
  readonly index: string;
  readonly eyebrow: string;
  readonly title: string;
  /** Paragraphs. Two: what it is, then why it is built that way. */
  readonly body: readonly string[];
  readonly points: readonly string[];
  /** Two or three, never more — a strip, not a table. */
  readonly metrics: readonly FeatureMetric[];
}

const VIEWPORT_VH = 100;

export const STAGES: readonly Stage[] = [
  { key: 'hero', vh: 100 },
  // Deliberately tall and deliberately sparse: this is where the tape itself is
  // the content, and it needs room to print before the first panel talks over it.
  { key: 'print', vh: 200 },
  // One stage per part of the product. They are long because the tape has to
  // keep moving underneath the copy — a short stage prints two candles and the
  // scene stalls while the reader is still on the first sentence. Roughly a
  // screen and a half of tape sits between one panel and the next, which is the
  // gap that makes the board read as the subject and the copy as the margin
  // note rather than the other way round.
  { key: 'ai', vh: 170 },
  { key: 'chat', vh: 170 },
  { key: 'live', vh: 170 },
  { key: 'heatmap', vh: 170 },
  { key: 'macro', vh: 170 },
  { key: 'ownership', vh: 170 },
  { key: 'social', vh: 170 },
  // No copy, on purpose. The last panel's annotations need room to finish, and
  // ending the page on the tape rather than on a pitch is the point.
  { key: 'tail', vh: 100 },
];

/** Total document height of the canvas track, in viewport heights. */
export const TRACK_VH = STAGES.reduce((sum, stage) => sum + stage.vh, 0);

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * Maps each stage onto the scroll span during which its top half is on screen.
 *
 * A section starting at `topVh` has its top edge at the middle of the viewport
 * once the page has scrolled `topVh - 50vh`, so that is the anchor. Anchoring on
 * the section top rather than on raw cumulative height is what keeps the canvas
 * in step with the copy: without the half-viewport correction every annotation
 * lands roughly half a screen before the panel that explains it.
 *
 * The resulting windows are monotonic, non-overlapping and cover [0, 1] — which
 * `stages.test.ts` asserts, because the whole schedule leans on it.
 */
function deriveWindows(stages: readonly Stage[]): readonly StageWindow[] {
  const scrollable = Math.max(TRACK_VH - VIEWPORT_VH, 1);
  const tops: number[] = [];
  let cursor = 0;
  for (const stage of stages) {
    tops.push(cursor);
    cursor += stage.vh;
  }
  const anchor = (topVh: number) => clamp01((topVh - VIEWPORT_VH / 2) / scrollable);

  return stages.map((stage, i) => ({
    key: stage.key,
    from: anchor(tops[i]),
    to: i + 1 < stages.length ? anchor(tops[i + 1]) : 1,
  }));
}

export const STAGE_WINDOWS: readonly StageWindow[] = deriveWindows(STAGES);

export function windowFor(key: StageKey): StageWindow {
  const found = STAGE_WINDOWS.find((w) => w.key === key);
  if (!found) throw new Error(`Unknown stage: ${key}`);
  return found;
}

/** Track progress after scrolling `vh` viewport heights from the top. */
export function progressAtVh(vh: number): number {
  return clamp01(vh / Math.max(TRACK_VH - VIEWPORT_VH, 1));
}

/**
 * Candles keep arriving for the whole page rather than only during the `print`
 * stage: a chart that finished a third of the way down would leave the feature
 * panels sitting over a frozen picture, and there would be nothing left to pan.
 * Printing completes exactly as the closing tail arrives.
 *
 * The start is stated in scroll distance rather than taken from the `print`
 * window, which would be half a screen down. A page whose one moving part does
 * nothing for the first 50vh reads as broken, not as restrained — so the tape
 * starts arriving within the first flick of the wheel. The hero copy stays
 * legible because the scrim's radial gradient covers the column it sits in.
 */
const PRINT_START_VH = 10;

export const PRINT_FROM = progressAtVh(PRINT_START_VH);
export const PRINT_TO = windowFor('tail').from;

/**
 * Printing is eased rather than linear. A linear print leaves the board looking
 * two-thirds empty for the first two panels — accurate to the schedule, and a
 * poor picture. This front-loads the fill so the chart reads as a chart early,
 * then slows to a trickle that keeps arriving under the feature copy.
 */
const PRINT_EASE = 0.7;

/**
 * How much of the series is already on the board before a pixel is scrolled.
 *
 * A tape that begins from nothing the moment someone opens the page is a demo
 * of a chart rather than a chart — the market was running long before the
 * visitor arrived. It is also the only honest way to fill the first screen: an
 * empty board is a large dark rectangle occupying the bottom half of it, and
 * the alternative is padding the hero with copy nobody asked for.
 *
 * A third, not more. Enough to fill the board's left side and give the price
 * scale something real to hold, little enough that the head of the tape still
 * visibly grows into empty space on the first scroll — which is the thing the
 * scroll has to be seen doing.
 */
const SEED_FRACTION = 0.35;

export function printedFraction(rawProgress: number): number {
  return SEED_FRACTION + (1 - SEED_FRACTION) * Math.pow(clamp01(rawProgress), PRINT_EASE);
}

/**
 * Progress at which candle `index` has finished printing. Inverts the easing.
 *
 * The seeded head answers 0: those bars are on the board before the page has
 * moved. Callers use this as a floor for when a mark may appear, so 0 is both
 * true and the safe direction to be wrong in.
 */
export function progressOfCandle(index: number, total: number): number {
  const target = (index + 1) / total;
  if (target <= SEED_FRACTION) return 0;

  const fraction = Math.pow((target - SEED_FRACTION) / (1 - SEED_FRACTION), 1 / PRINT_EASE);
  return PRINT_FROM + fraction * (PRINT_TO - PRINT_FROM);
}

/** A sub-window inside a stage, expressed as fractions of that stage. */
export function within(
  key: StageKey,
  startFrac: number,
  endFrac: number
): {
  from: number;
  to: number;
} {
  const w = windowFor(key);
  const span = w.to - w.from;
  return { from: w.from + span * startFrac, to: w.from + span * endFrac };
}

export const FEATURES: readonly Feature[] = [
  {
    key: 'ai',
    index: '01',
    eyebrow: 'Analysis',
    title: 'Reports you can audit',
    body: [
      'Oracle-X gathers the evidence before it writes anything. The price history, the on-chain readings, the filings and the news that actually moved the name are pulled and cited first; only then is the argument built, and it is built against that evidence rather than around it.',
      'A second pass then reads the draft the way a sceptic would — hunting for the claim with nothing underneath it, the number that contradicts the conclusion, the risk the first pass talked straight past. What reaches you is the reviewed version, and every line in it still points back at the row it came from.',
    ],
    points: [
      'Evidence gathered and cited before the first sentence',
      'A review pass argues against the draft before you see it',
      'Every claim links back to the row it came from',
      'Local models by default, hosted ones when you want them',
    ],
    metrics: [
      { value: '3', label: 'passes per report' },
      { value: String(LLM.presets), label: 'LLM providers' },
      { value: 'local', label: 'first, via Ollama' },
    ],
  },
  {
    key: 'chat',
    index: '02',
    eyebrow: 'Oracle chat',
    title: 'Ask it in plain language',
    body: [
      'Chat runs on the same data the charts are drawn from, so an answer arrives with the rows behind it instead of a summary of them. Ask why a level held and you get the level, the volume that defended it and the funding at the time — not a paragraph about support and resistance.',
      'Retrieval keeps the conversation as vector memory rather than as a rolling transcript, so a thesis you laid out three sessions ago is still context today. Answers come back short or worked through depending on which you ask for; what sits underneath them does not change.',
    ],
    points: [
      'Answers carry the rows they were built from',
      'History kept as vector memory, not a rolling transcript',
      'Concise or worked through, switched per question',
      'The same data as the charts — no second, staler copy',
    ],
    metrics: [
      { value: 'RAG', label: 'vector memory' },
      { value: '2', label: 'response modes' },
    ],
  },
  {
    key: 'live',
    index: '03',
    eyebrow: 'Market data',
    title: 'Crypto and US equities on one board',
    body: [
      'On-chain metrics, perpetual funding and the liquidation flow sit next to NASDAQ names — same screen, same clock. The point is not that all of it is available somewhere; it is that a funding flush and an equity gap stop being two separate stories you read an hour apart.',
      'Prices arrive over a WebSocket, so the board moves when the market moves rather than on whatever interval a poller happened to be set to. Liquidations print as they happen, which is the only state in which that particular number tells you anything.',
    ],
    points: [
      'On-chain metrics and perpetual funding side by side',
      'Liquidation flow as it prints, not as a daily total',
      'WebSocket stream rather than interval polling',
      'One clock across crypto and the US session',
    ],
    metrics: [
      { value: 'WS', label: 'streaming prices' },
      { value: '24/7', label: 'crypto + US session' },
    ],
  },
  {
    key: 'heatmap',
    index: '04',
    eyebrow: 'Screening',
    title: 'See the rotation, then find the name',
    body: [
      'One heatmap covers both markets on a single colour scale, so where money is moving is something you notice on the way past rather than something you set out to reconstruct. Two maps with two ranges are two pictures; this is one picture.',
      'The full crypto universe is tagged by sector alongside the equity map, and a sector opens straight into the names inside it. Getting from "money is leaving this" to the specific ticker is one click, without switching tools or losing the frame you were reading.',
    ],
    points: [
      'Crypto and equities on a single colour scale',
      'Full crypto universe, tagged by sector',
      'Sector to ticker in one click',
      'Rotation read at a glance, not reconstructed',
    ],
    metrics: [
      { value: '2', label: 'markets, one scale' },
      { value: '1', label: 'click to the name' },
    ],
  },
  {
    key: 'macro',
    index: '05',
    eyebrow: 'Macro context',
    title: 'The reason behind the move',
    body: [
      'A calendar of the releases that actually reprice risk — rates, inflation, liquidity — rather than every scheduled number that happens to exist. What matters is which prints have moved the board you are watching, and that is a much shorter list than the one most calendars hand you.',
      'News attribution then ties a specific move back to what caused it, so a red candle arrives as a consequence you can name instead of a surprise you rationalise afterwards. The backdrop sits beside the chart while you are reading it, not in a tab you open once things have already gone wrong.',
    ],
    points: [
      'Calendar filtered to the events that actually reprice',
      'News attribution mapped onto the move it explains',
      'Rate, inflation and liquidity backdrop beside price',
      'Context in place before the move, not after it',
    ],
    metrics: [{ value: 'why', label: 'attached to the move' }],
  },
  {
    key: 'ownership',
    index: '06',
    eyebrow: 'Positioning',
    title: 'Who owns it, and who is leaving',
    body: [
      'Institutional ownership per name, tracked across filings instead of shown as one snapshot. A single filing tells you who holds it; the sequence tells you who is building, who is quietly trimming and who left in the quarter nobody was looking.',
      'New positions, exits and how concentrated the register is, held next to the price rather than filed away from it. A level holds or breaks for a reason, and often enough the reason is on this board before it is visible on the chart.',
    ],
    points: [
      'Ownership board for every covered name',
      'Position changes tracked across filings, not a snapshot',
      'Concentration and holder-level detail',
      'Read beside price, where it actually means something',
    ],
    metrics: [
      { value: 'Δ', label: 'positions over time' },
      { value: '13F', label: 'filing coverage' },
    ],
  },
  {
    key: 'social',
    index: '07',
    eyebrow: 'Community',
    title: 'Theses argued in the open',
    body: [
      'Post a call, put the reasoning under it and defend it in the replies. A thesis that has survived being argued with is worth more than one nobody read, which is the whole reason this lives inside the terminal rather than on a different site entirely.',
      'Profiles are public and carry their history — the calls that worked and the ones that did not — so following someone is a decision you make on a record instead of on a follower count. Watchlists are shareable rather than locked to the account that made them.',
    ],
    points: [
      'Posts with threaded discussion, not a comment box',
      'Public profiles that carry the whole record',
      'Follow on track record, not on follower count',
      'Watchlists you can hand to someone else',
    ],
    metrics: [
      { value: 'open', label: 'profiles and history' },
      { value: 'shared', label: 'watchlists' },
    ],
  },
];
