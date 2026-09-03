'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistViopMapNoteResponse } from '@/lib/bist-api';
import { VIOP_MAP_STANCE_LABEL, VIOP_MAP_STANCE_TONE, viopMapChips } from '@/lib/bist-viop';

interface ViopMapNoteProps {
  data: BistViopMapNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What one underlying's field says, above the map that draws it.
 *
 * The map is a picture of margin bands and the reader has to work out cold
 * that the streak below price is the long side's, that it is five percent
 * away, and that the newest session added to the other side. The header
 * states the first two from figures computed in Python; the sentence beneath
 * it states the third, when the model answers.
 *
 * The header renders whether or not the sentence arrives, which is the point
 * of the split — a model outage costs a paragraph rather than turning a
 * correct field into one that looks broken. Its own component rather than a
 * shared one, on the reasoning `ViopNote` records.
 *
 * The footer is not decoration. Every visitor to a "liquidation map" arrives
 * expecting one, and this page draws scan ranges instead; the one sentence a
 * reader must not leave without is the one saying so, in their line of sight.
 */
export default function ViopMapNote({ data, isLoading }: ViopMapNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;

  // The book could not be built, or is too thin to draw — and the page has
  // already said which on its own. A rendered-but-empty panel here would be
  // claiming a quiet field over a message that says there is none.
  if (!facts) return null;

  const chips = viopMapChips(facts);

  return (
    <section
      aria-label={`${facts.ticker} teminat haritası yapay zekâ okuması`}
      className="surface ai-surface px-4 py-3"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${VIOP_MAP_STANCE_TONE[facts.stance]}`}>
            {VIOP_MAP_STANCE_LABEL[facts.stance]}
          </span>

          <span className="text-xs text-fg-subtle">
            {facts.ticker} · {facts.book.expiries} vade · {facts.window.covered}/
            {facts.window.requested} seans
          </span>

          {chips.map((chip) => (
            <span
              key={chip.text}
              title={chip.title}
              className="tabnum font-mono text-xs text-fg-subtle"
            >
              {chip.text}
            </span>
          ))}

          {facts.stale && <span className="text-2xs text-warn">arşiv geride</span>}
        </div>

        <AiNote aiNote={data?.note} />

        <p className="text-2xs text-fg-subtle">
          Bantlar Takasbank&apos;ın tarama aralığıdır; teminat tamamlama çağrısının tetiklendiği
          seviye yayımlanmadığı için hesaplanamaz. Uzaklıklar {facts.as_of} spot kapanışına göredir.
          Ölçmedikleri: {facts.not_measured.join(', ')}.
        </p>
      </div>
    </section>
  );
}
