'use client';

import { MacroRatio } from '@/lib/api';
import { UNKNOWN, formatRatio } from './format';

/**
 * What each ratio is actually watched for. Static text, not a reading: these are
 * definitions of the measure, and nothing here claims which way today's value
 * leans — the board has no historical series to judge that against.
 */
const RATIO_CAPTIONS: Record<string, string> = {
  gold_silver: 'Ounces of silver per ounce of gold',
  gold_oil: 'Barrels of crude per ounce of gold',
  copper_gold: 'Growth appetite against safety',
};

/**
 * The three quotients a macro reader takes before reading any single price.
 *
 * Derived entirely from prices already on the board, so this strip costs nothing
 * upstream. A ratio missing a leg keeps its cell and shows an em dash: dropping
 * it would quietly change the shape of the row and hide the gap.
 */
export default function MacroRatios({ ratios }: { ratios: MacroRatio[] }) {
  if (!ratios.length) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[...Array(3)].map((_, index) => (
          <div key={index} className="surface h-[92px] shimmer" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {ratios.map((ratio) => {
        const isKnown = ratio.value !== null;
        return (
          <div key={ratio.key} className="surface p-4">
            <div className="label">{ratio.label}</div>
            <div className="mt-2">
              <span
                className={`text-xl font-mono tabnum ${isKnown ? 'text-fg' : 'text-fg-subtle'}`}
              >
                {isKnown ? formatRatio(ratio.value as number, ratio.decimals) : UNKNOWN}
              </span>
            </div>
            <div className="mt-1 text-sm text-fg-subtle truncate" title={ratio.caption}>
              {isKnown ? (RATIO_CAPTIONS[ratio.key] ?? ratio.caption) : 'Unavailable'}
            </div>
          </div>
        );
      })}
    </div>
  );
}
