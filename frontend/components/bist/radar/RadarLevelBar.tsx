import type { RadarLevels } from '@/lib/bist-api';
import { formatTry } from '@/lib/bist-format';
import { levelMarks } from '@/lib/bist-radar';

/**
 * Stop, entry band, price and targets on one horizontal line.
 *
 * Drawn to scale from the stop at the left to the furthest target at the
 * right, so the reader sees the shape of the trade — how thin the band is,
 * how far the first target sits — before reading a single figure. Renders
 * nothing when the levels do not span a range; a bar with every mark at one
 * end is a picture of nothing.
 */
export default function RadarLevelBar({ levels }: { levels: RadarLevels }) {
  const marks = levelMarks(levels);
  if (!marks) return null;

  const pct = (fraction: number) => `${(fraction * 100).toFixed(1)}%`;

  return (
    <div className="space-y-1">
      <div className="relative h-6">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line" />
        <div
          className="absolute top-1/2 h-2.5 -translate-y-1/2 rounded-sm bg-up/25"
          style={{
            left: pct(marks.entryLow),
            width: pct(Math.max(0.01, marks.entryHigh - marks.entryLow)),
          }}
          title={`Giriş bandı ${formatTry(levels.entry_low)} – ${formatTry(levels.entry_high)}`}
        />
        <Mark at={marks.stop} tone="bg-down" title={`Stop ${formatTry(levels.stop)}`} />
        <Mark at={marks.target1} tone="bg-up" title={`Hedef 1 ${formatTry(levels.target1)}`} />
        {marks.target2 !== null && levels.target2 !== null && (
          <Mark at={marks.target2} tone="bg-up/60" title={`Hedef 2 ${formatTry(levels.target2)}`} />
        )}
        <div
          className="absolute top-0 h-6 w-0.5 -translate-x-1/2 bg-fg"
          style={{ left: pct(marks.price) }}
          title={`Fiyat ${formatTry(levels.price)}`}
        />
      </div>
      <div className="flex justify-between text-2xs tabnum text-fg-subtle">
        <span className="text-down">Stop {formatTry(levels.stop)}</span>
        <span>
          Giriş {formatTry(levels.entry_low)}–{formatTry(levels.entry_high)}
        </span>
        <span className="text-up">
          Hedef {formatTry(levels.target1)}
          {levels.target2 !== null ? ` · ${formatTry(levels.target2)}` : ''}
        </span>
      </div>
    </div>
  );
}

function Mark({ at, tone, title }: { at: number; tone: string; title: string }) {
  return (
    <div
      className={`absolute top-1/2 h-3 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm ${tone}`}
      style={{ left: `${(at * 100).toFixed(1)}%` }}
      title={title}
    />
  );
}
