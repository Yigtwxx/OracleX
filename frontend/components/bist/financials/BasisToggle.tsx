'use client';

import { AlertTriangle } from 'lucide-react';

import ToggleGroup from '@/components/ui/ToggleGroup';
import type { BistDeflation } from '@/lib/bist-api';
import { type Basis, basisAvailable, basisNotice } from '@/lib/bist-financials';

/**
 * Which lira the board is quoted in.
 *
 * Disabled rather than merely defaulted away from when nothing could be
 * deflated. A toggle that silently answers "nominal" to a press on "Reel" is
 * worse than no toggle: the reader believes they are looking at purchasing
 * power. So the control goes dead and the reason is printed beside it.
 */
export default function BasisToggle({
  deflation,
  basis,
  onChange,
}: {
  deflation: BistDeflation;
  basis: Basis;
  onChange: (next: Basis) => void;
}) {
  const available = basisAvailable(deflation);
  const notice = basisNotice(deflation);

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {available ? (
        <ToggleGroup
          label="Fiyat çerçevesi"
          options={[
            { value: 'real', label: 'Reel' },
            { value: 'nominal', label: 'Nominal' },
          ]}
          value={basis}
          onChange={(next) => onChange(next as Basis)}
        />
      ) : (
        <span className="label" role="status">
          Nominal
        </span>
      )}

      {notice && (
        <span
          className={`flex items-start gap-1.5 text-2xs leading-relaxed ${
            notice.tone === 'warn' ? 'text-warn' : 'text-fg-subtle'
          }`}
        >
          {notice.tone === 'warn' && (
            <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
          )}
          {notice.text}
        </span>
      )}
    </div>
  );
}
