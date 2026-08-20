'use client';

import { IdentityBarClasses } from '@/lib/assetIdentity';
import { formatPrice, rangePosition } from './format';

interface RangeBarProps {
  price: number | null;
  low: number | null;
  high: number | null;
  /** `full` labels both ends; `compact` is the unlabelled row variant. */
  variant?: 'full' | 'compact';
  /**
   * The instrument's own colour, where it has one. Identity, not direction —
   * the bar is gold-coloured on the gold row whether gold is up or down.
   */
  accent?: IdentityBarClasses;
}

/**
 * Where the current price sits in its 52-week range.
 *
 * The single most useful thing to know about a commodity that a price alone
 * cannot tell you: gold at 4,377 means nothing until you see it is near the top
 * of its year, and copper at 6.69 means a lot once you see it is at the ceiling.
 *
 * Renders nothing when the range is unknown. A bar with an arbitrarily placed
 * marker would be read as a measurement, and there is no honest neutral position
 * to fall back to — the midpoint is itself a claim.
 */
export default function RangeBar({ price, low, high, variant = 'compact', accent }: RangeBarProps) {
  const position = rangePosition(price, low, high);
  if (position === null) return null;

  const percent = position * 100;

  // The hue is dimmed on the fill and left at full strength on the marker, which
  // keeps the existing hierarchy: the marker is the reading, the fill only
  // reinforces it. `opacity-40` rather than a `/40` colour modifier because the
  // palette is `var()`-based and Tailwind cannot compute alpha on those.
  const fillClass = accent ? `${accent.fill} opacity-40` : 'bg-line-strong';
  const markerClass = accent ? accent.marker : 'bg-fg';

  return (
    <div className="w-full">
      <div className="relative h-1 rounded-full bg-surface-2" aria-hidden="true">
        {/* The filled portion is decorative reinforcement of the marker, not a
            second reading — same colour family, lower contrast. */}
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${fillClass}`}
          style={{ width: `${percent}%` }}
        />
        <div
          className={`absolute top-1/2 w-1.5 h-1.5 -mt-[3px] -ml-[3px] rounded-full ${markerClass}`}
          style={{ left: `${percent}%` }}
        />
      </div>

      {variant === 'full' && (
        <div className="mt-1 flex items-center justify-between text-2xs font-mono tabnum text-fg-subtle">
          <span>{formatPrice(low as number)}</span>
          <span className="text-fg-subtle">52w</span>
          <span>{formatPrice(high as number)}</span>
        </div>
      )}
    </div>
  );
}
