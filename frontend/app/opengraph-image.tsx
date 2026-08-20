import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { ImageResponse } from 'next/og';

/**
 * The card a pasted Oracle-X link unfurls into, on X, Slack, Discord, iMessage.
 *
 * Rendered rather than exported as a PNG so the copy and the palette stay tied
 * to the source: the headline is the landing page's own headline, the light is
 * the landing page's own light, and neither can drift out of sync with a binary
 * checked in beside them.
 *
 * Scoped to the marketing world, not the terminal's: `--accent` on `/` is white
 * and the up/down pair sits one step brighter, which is what this card inherits.
 */
export const runtime = 'nodejs';

export const alt = 'Oracle-X — a financial intelligence terminal for crypto and US equities';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

// Marketing palette — globals.css › LANDING.
const BG = '#0a0a0c';
const FG = '#e8e8ea';
const FG_MUTED = '#9a9aa3';
const HAIRLINE = 'rgba(255, 255, 255, 0.09)';
const UP = '#26d366';

/**
 * The reticle-and-X from `app/icon.svg`, minus the favicon's rounded plate —
 * on a full-bleed near-black field that plate would read as a chip sitting on
 * the card rather than as the mark itself.
 */
function Mark({
  size,
  color,
  strokeScale = 1,
}: {
  size: number;
  color: string;
  strokeScale?: number;
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <g stroke={color} fill="none" strokeLinecap="round">
        <g strokeWidth={2.4 * strokeScale}>
          <path d="M12.63 7.66A9 9 0 0 1 19.37 7.66" />
          <path d="M24.34 12.63A9 9 0 0 1 24.34 19.37" />
          <path d="M19.37 24.34A9 9 0 0 1 12.63 24.34" />
          <path d="M7.66 19.37A9 9 0 0 1 7.66 12.63" />
        </g>
        <g strokeWidth={2.1 * strokeScale}>
          <path d="M7.09 7.09L24.91 24.91" />
          <path d="M24.91 7.09L7.09 24.91" />
        </g>
      </g>
    </svg>
  );
}

/**
 * The write head from `.landing-caret`: a candle, not a block cursor. The page's
 * one recurring object is a bar with a wick, so the thing that sits at the end
 * of a line being written is that, at the size of the line it is writing.
 */
function Caret({ fontSize }: { fontSize: number }) {
  const width = fontSize * 0.42;
  const height = fontSize * 0.9;
  return (
    <div
      style={{ display: 'flex', position: 'relative', width, height, marginLeft: fontSize * 0.3 }}
    >
      {/* Wick */}
      <div
        style={{
          position: 'absolute',
          left: width / 2 - 0.5,
          top: 0,
          width: 1.5,
          height,
          backgroundColor: UP,
          opacity: 0.7,
        }}
      />
      {/* Body */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: height * 0.25,
          width,
          height: height * 0.5,
          backgroundColor: UP,
        }}
      />
    </div>
  );
}

const TABS = ['OVERVIEW', 'MACRO', 'LIVE', 'OWNERSHIP', 'ANALYSIS', 'CHAT', 'HEATMAP'];

export default async function Image() {
  const [regular, bold] = await Promise.all([
    readFile(join(process.cwd(), 'assets/og/JetBrainsMono-Regular.subset.ttf')),
    readFile(join(process.cwd(), 'assets/og/JetBrainsMono-Bold.subset.ttf')),
  ]);

  const HEADLINE = 58;

  return new ImageResponse(
    <div
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        width: '100%',
        height: '100%',
        padding: 64,
        backgroundColor: BG,
        fontFamily: 'JetBrains Mono',
        color: FG,
      }}
    >
      {/* The room, lit by the tape that prints in it — globals.css ›
            .landing-glow. No white wash: on a near-black field that only lifts
            the ground to grey and takes the mark's contrast with it. */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          // `--up` at 11% and `--down` at 9%, written out because satori has no
          // `color-mix`. Both stay under the ceiling the landing page sets: a
          // wash that competes with the mark is too strong.
          backgroundImage:
            'radial-gradient(56% 62% at 18% 84%, rgba(38, 211, 102, 0.11), transparent 72%), radial-gradient(52% 58% at 86% 18%, rgba(243, 73, 73, 0.09), transparent 74%)',
        }}
      />

      {/* The mark as an object in the room rather than a logo in a corner:
            oversized, cropped by the right edge, and sitting in the red wash so
            it is lit from behind instead of drawn on top. */}
      {/* Stroke scaled back to a hairline rather than left proportional: at this
            size the mark's own 2.4 weight resolves to a 26px bar, and the four
            reticle arcs stop reading as an aperture and start reading as four
            rounded blobs. Held near 6px they read as what they are — marks
            drawn on an instrument. */}
      <div style={{ display: 'flex', position: 'absolute', top: 34, right: -178 }}>
        <Mark size={600} color="rgba(255, 255, 255, 0.1)" strokeScale={0.14} />
      </div>

      {/* Identity */}
      <div style={{ display: 'flex', alignItems: 'center', position: 'relative' }}>
        <Mark size={40} color={FG} />
        <span
          style={{
            marginLeft: 16,
            fontSize: 21,
            fontWeight: 700,
            letterSpacing: '0.2em',
            color: FG,
          }}
        >
          ORACLE-X
        </span>
      </div>

      {/* Claim. The eyebrow says what this is, the headline says what is
            different about it — the same division of labour as the hero. */}
      <div style={{ display: 'flex', flexDirection: 'column', position: 'relative' }}>
        <span style={{ fontSize: 16, letterSpacing: '0.22em', color: FG_MUTED }}>
          FINANCIAL INTELLIGENCE TERMINAL
        </span>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            marginTop: 26,
            fontSize: HEADLINE,
            fontWeight: 700,
            lineHeight: 1.14,
            letterSpacing: '-0.03em',
          }}
        >
          <span>Analysis you can</span>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span>check line by line.</span>
            <Caret fontSize={HEADLINE} />
          </div>
        </div>
      </div>

      {/* What is behind the link: the board's own tabs, in the terminal's
            micro-label voice. Real product surface, not invented figures — a
            card that prints prices is a card that will be wrong by the time
            anybody sees it. */}
      <div style={{ display: 'flex', flexDirection: 'column', position: 'relative' }}>
        <div style={{ display: 'flex', width: '100%', height: 1, backgroundColor: HAIRLINE }} />
        <div style={{ display: 'flex', alignItems: 'center', marginTop: 22 }}>
          {TABS.map((tab, i) => (
            <div key={tab} style={{ display: 'flex', alignItems: 'center' }}>
              {/* Neutral, not tinted: in this system a red mark means a decline,
                  and a separator that means nothing has no business borrowing
                  the colour that does. */}
              {i > 0 && (
                <span style={{ margin: '0 14px', fontSize: 14, color: FG_MUTED, opacity: 0.5 }}>
                  ·
                </span>
              )}
              <span style={{ fontSize: 14, letterSpacing: '0.18em', color: FG_MUTED }}>{tab}</span>
            </div>
          ))}
        </div>
      </div>
    </div>,
    {
      ...size,
      fonts: [
        { name: 'JetBrains Mono', data: regular, weight: 400, style: 'normal' },
        { name: 'JetBrains Mono', data: bold, weight: 700, style: 'normal' },
      ],
    }
  );
}
