'use client';

import { useEffect, useMemo, useState } from 'react';

import { buildRamp } from '@/lib/heat-ramp';
import { FALLBACK, readPalette, type Palette } from '@/lib/chart-palette';

function Swatch({ colour, label }: { colour: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span aria-hidden="true" className="h-2 w-3 rounded-sm" style={{ background: colour }} />
      <span className="text-fg-muted">{label}</span>
    </span>
  );
}

/**
 * The ramp itself, plus the two marks that sit on top of it.
 *
 * A gradient bar rather than swatches, because the field is continuous: five
 * boxes would imply five buckets the data does not have. Its ends are labelled
 * with what the intensity means rather than with numbers — the scale is
 * relative to this symbol's own busiest level, so an absolute figure would be
 * a different quantity on every board.
 */
export default function ViopMapLegend({ hasProfile }: { hasProfile: boolean }) {
  const [palette, setPalette] = useState<Palette>(FALLBACK);
  useEffect(() => setPalette(readPalette()), []);

  const gradient = useMemo(() => {
    const ramp = buildRamp(
      [
        palette['--heat-seq-1'],
        palette['--heat-seq-2'],
        palette['--heat-seq-3'],
        palette['--heat-seq-4'],
        '#22d3ee',
      ],
      12
    );
    return `linear-gradient(to right, ${ramp.join(', ')})`;
  }, [palette]);

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs">
      <span className="flex items-center gap-1.5">
        <span className="text-fg-subtle">az</span>
        <span
          aria-hidden="true"
          className="h-2 w-24 rounded-sm border border-line"
          style={{ background: gradient }}
        />
        <span className="text-fg-subtle">çok</span>
        <span className="text-fg-muted">o fiyatta duran pozisyon</span>
      </span>
      <span className="flex items-center gap-1">
        <span
          aria-hidden="true"
          className="h-2 w-1.5 rounded-[1px]"
          style={{ background: palette['--up'] }}
        />
        <span
          aria-hidden="true"
          className="h-2 w-1.5 rounded-[1px]"
          style={{ background: palette['--down'] }}
        />
        <span className="text-fg-muted">Spot mumları</span>
      </span>
      {hasProfile && (
        <>
          <Swatch colour={palette['--heat-seq-4']} label="En çok işlem gören fiyat" />
          <Swatch colour={palette['--fg-muted']} label="Değer alanı %70" />
        </>
      )}
    </div>
  );
}
