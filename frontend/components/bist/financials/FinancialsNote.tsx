'use client';

import AiNote from '@/components/ui/AiNote';
import type { AiNote as AiNoteShape } from '@/lib/ai-note';
import type { BistFinancials } from '@/lib/bist-api';
import { financialsChips } from '@/lib/bist-financials';

/**
 * The model's read, above the charts.
 *
 * The chips are computed here in TypeScript and the paragraph is not: the
 * layout, the newest period and the price frame are facts the board already
 * knows, and a model asked to restate them is a model given three chances to
 * get them wrong. It explains; it does not classify.
 */
export default function FinancialsNote({
  payload,
  note,
  isLoading,
}: {
  payload: BistFinancials | undefined;
  note: AiNoteShape | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <div className="surface shimmer h-[92px]" />;
  if (!payload) return null;

  return (
    <section
      aria-label="Bilanço yapay zekâ okuması"
      className="surface ai-surface space-y-2 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {financialsChips(payload).map((chip) => (
          <span
            key={chip.text}
            title={chip.title}
            className="rounded border border-line px-1.5 py-px text-2xs text-fg-muted"
          >
            {chip.text}
          </span>
        ))}
      </div>

      <AiNote aiNote={note} />

      <p className="text-2xs leading-relaxed text-fg-subtle">
        Ölçmedikleri: bu sayfa yalnızca İş Yatırım&apos;ın yayımladığı tabloları okur. Şirketin
        işini, sözleşmelerini, sektörünü veya haberlerini bilmez; değerleme yapmaz ve sonraki
        çeyreği tahmin etmez.
      </p>
    </section>
  );
}
