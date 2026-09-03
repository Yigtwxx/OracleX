'use client';

import { EMPTY, formatCompact, formatPercent, formatSignedPercent } from '@/lib/bist-format';
import type { UnderlyingBar } from '@/lib/bist-viop';

interface ViopOpenInterestBarsProps {
  bars: UnderlyingBar[];
  selected?: string;
  onSelect: (underlying: string | undefined) => void;
  height?: number;
}

/**
 * Where the outstanding interest actually sits, by underlying.
 *
 * The panel exists because the strip of tiles above it can only show four names
 * and this board lists forty. A reader who sees USDTRY, the index and two banks
 * in the tiles has no way to know whether the rest is another half of the book
 * or a rounding error — and on this exchange it is usually the second, which is
 * the finding rather than a footnote.
 *
 * DOM rather than a chart library, for the same reason `RangeDistribution` is:
 * every row is a focusable, pressable control that filters the whole page, and
 * that is cheaper and more accurate as an element than as a canvas with a
 * hit-test bolted on.
 *
 * Length is the book and colour is the direction its open interest moved — the
 * pairing the panel exists for. A long bar is a crowded contract; a long bar
 * that turned red is a crowded contract people are leaving, and neither figure
 * says that alone. Colour means direction here exactly as it does everywhere
 * else on the realm, never category.
 */
export default function ViopOpenInterestBars({
  bars,
  selected,
  onSelect,
  height = 300,
}: ViopOpenInterestBarsProps) {
  const measured = bars.filter((bar) => bar.openInterest !== null);
  const largest = measured.reduce((max, bar) => Math.max(max, bar.openInterest ?? 0), 0);

  if (measured.length === 0) {
    return (
      <p
        style={{ height }}
        className="flex items-center justify-center px-4 text-center text-sm text-fg-subtle"
      >
        Açık pozisyon yayımlayan sözleşme yok.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1 overflow-y-auto custom-scrollbar p-3" style={{ height }}>
      <p className="sr-only">
        {measured.length} dayanağın toplam açık pozisyonu, büyükten küçüğe. Renk açık pozisyonun
        günlük yönünü gösterir.
      </p>

      {bars.map((bar) => {
        const active = selected === bar.underlying;
        // A name whose column came back empty still gets a row: it is listed,
        // and drawing nothing for it would read as a book of zero rather than
        // as an unread figure.
        const unread = bar.openInterest === null;
        const width =
          largest > 0 && !unread
            ? Math.max(1.5, ((bar.openInterest as number) / largest) * 100)
            : 0;
        const label = unread
          ? `${bar.underlying}: açık pozisyon yayımlanmadı, ${bar.expiries} vade`
          : `${bar.underlying}: ${formatCompact(bar.openInterest, 1)} sözleşme, tahtanın ${formatPercent(bar.share, 1)}'i, ${bar.expiries} vade`;

        return (
          <button
            key={bar.underlying}
            type="button"
            aria-pressed={active}
            aria-label={label}
            title={label}
            onClick={() => onSelect(active ? undefined : bar.underlying)}
            className={`group grid grid-cols-[72px_1fr_auto] items-center gap-2 rounded-sm px-1 py-0.5 text-left transition-colors ${
              active ? 'bg-surface-2' : 'hover:bg-surface-2/60'
            }`}
          >
            <span
              className={`truncate text-2xs ${active ? 'text-fg' : 'text-fg-muted group-hover:text-fg'}`}
            >
              {bar.underlying}
            </span>

            <span className="flex h-3 items-center">
              {unread ? (
                <span className="text-2xs text-fg-subtle">yayımlanmadı</span>
              ) : (
                <span
                  className="h-full rounded-sm"
                  style={{
                    width: `${width}%`,
                    background: fillFor(bar),
                    outline: active ? '1px solid var(--fg)' : undefined,
                  }}
                />
              )}
            </span>

            <span className="tabnum flex items-baseline gap-1.5 text-2xs">
              <span className="text-fg-muted">{formatCompact(bar.openInterest, 1)}</span>
              <span className={`w-12 text-right ${toneOf(bar)}`}>
                {bar.changeRatio === null ? EMPTY : formatSignedPercent(bar.changeRatio, 1)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The direction open interest moved, as a tint that saturates with the move.
 *
 * A book that did not move at all is drawn in the neutral border colour rather
 * than a pale green: "unchanged" is a real reading on this board — a contract
 * nobody opened or closed — and giving it a direction would invent one.
 */
function fillFor(bar: UnderlyingBar): string {
  if (bar.changeRatio === null || bar.changeRatio === 0) return 'var(--border-strong)';
  // Five percent of yesterday's book is a large day for an underlying, so the
  // ramp saturates there rather than at a figure only the index strip reaches.
  const strength = Math.round((0.35 + Math.min(1, Math.abs(bar.changeRatio) / 0.05) * 0.55) * 100);
  const token = bar.changeRatio > 0 ? 'var(--up)' : 'var(--down)';
  return `color-mix(in srgb, ${token} ${strength}%, transparent)`;
}

function toneOf(bar: UnderlyingBar): string {
  if (bar.changeRatio === null || bar.changeRatio === 0) return 'text-fg-subtle';
  return bar.changeRatio > 0 ? 'text-up' : 'text-down';
}
