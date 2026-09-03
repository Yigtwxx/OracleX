'use client';

import { useId } from 'react';

interface BriefChartProps {
  /** Closes, oldest first. */
  data: number[];
  positive: boolean;
  support: number | null;
  resistance: number | null;
  height?: number;
}

/**
 * The expanded card's chart: the same series the collapsed card sparks, drawn
 * large enough to carry the levels on top of it.
 *
 * Inline SVG rather than ECharts, which the project has and which this could
 * have used. Two reasons it does not. The chart has no axes, no tooltip and no
 * zoom — everything ECharts is for — so it would be several hundred kilobytes
 * of interaction code to draw one filled path. And the levels are the point:
 * they have to sit in the same coordinate space as the line, and hand-drawing
 * both is what guarantees they do.
 *
 * A level outside the series' own range is not drawn. Clamping it to the top of
 * the chart would put a resistance line above a price that never went near it,
 * which reads as "we tested this and held" — a claim the data does not make.
 */
export default function BriefChart({
  data,
  positive,
  support,
  resistance,
  height = 120,
}: BriefChartProps) {
  const gradientId = useId();
  if (data.length < 2) return null;

  const width = 300;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  // A little headroom so the line does not sit flush against the frame, and so
  // a level near the extreme still has somewhere to be drawn.
  const pad = range * 0.08;
  const lo = min - pad;
  const span = range + pad * 2;

  const y = (value: number) => height - ((value - lo) / span) * height;
  const x = (index: number) => (index / (data.length - 1)) * width;

  const line = data.map((value, index) => `${x(index)},${y(value)}`).join(' ');
  const area = `${x(0)},${height} ${line} ${x(data.length - 1)},${height}`;
  const stroke = positive ? 'var(--up)' : 'var(--down)';

  const levels = [
    { value: support, color: 'var(--up)', label: 'S' },
    { value: resistance, color: 'var(--down)', label: 'R' },
  ].filter((level): level is { value: number; color: string; label: string } => {
    const { value } = level;
    return value !== null && value >= lo && value <= lo + span;
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-full w-full"
      role="img"
      aria-label={`Price over the recent window, ${positive ? 'up' : 'down'} across it`}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>

      <polygon points={area} fill={`url(#${gradientId})`} />

      {levels.map((level) => (
        <g key={level.label}>
          <line
            x1={0}
            x2={width}
            y1={y(level.value)}
            y2={y(level.value)}
            stroke={level.color}
            strokeWidth="1"
            strokeDasharray="4 4"
            opacity="0.55"
            // The viewBox is stretched horizontally to fill the card, which
            // would stretch the dashes with it. This keeps them square.
            vectorEffect="non-scaling-stroke"
          />
        </g>
      ))}

      <polyline
        points={line}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
