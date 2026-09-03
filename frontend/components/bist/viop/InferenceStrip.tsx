'use client';

import { AlertTriangle } from 'lucide-react';

import type { ViopMapModel } from '@/lib/bist-api';
import { formatCompactTry } from '@/lib/bist-format';

/**
 * The one thing on this page that is inferred, said above the chart.
 *
 * Not a tooltip, and not dismissible. The crypto liquidation board puts its
 * equivalent behind an info icon, which is defensible there because that model
 * is inference end to end and a reader knows it. Here the opposite is true:
 * every other input — the exposure, the entry price, the swept range, the band
 * distance — is published, which makes the single inferred axis the one most
 * likely to be mistaken for a measurement.
 *
 * One line, inside the card's chrome rather than floating above it as a boxed
 * callout. The first version was a bordered panel two lines deep, which pushed
 * the chart under the fold and made the warning read as an error state. It has
 * to be unmissable, not loud.
 *
 * The sentence carries this symbol's own numbers rather than generic wording,
 * so it reads as a fact about the board in front of the reader instead of as
 * boilerplate to scroll past.
 */
export default function InferenceStrip({ model }: { model: ViopMapModel }) {
  return (
    <div className="flex items-baseline gap-2 border-b border-line px-3 py-1.5">
      <AlertTriangle className="h-3 w-3 shrink-0 translate-y-0.5 text-warn" aria-hidden="true" />
      <p className="text-2xs leading-relaxed text-fg-muted">
        <span className="font-semibold text-fg">Yön çıkarımdır, veri değildir.</span> Açık pozisyon
        artışı, uzlaşma fiyatı o gün yükseldiyse <span className="text-up">uzun</span>, düştüyse{' '}
        <span className="text-down">kısa</span> sayılır — VİOP kırılımı yayınlamaz. Fiyatın
        değişmediği{' '}
        <span className="tabnum text-fg">
          {model.undirected_sessions} seansta ({formatCompactTry(model.undirected_notional)})
        </span>{' '}
        yön atanmadı; o pozisyonlar haritada yok.
      </p>
    </div>
  );
}
