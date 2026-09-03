'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistViopNoteResponse } from '@/lib/bist-api';
import { VIOP_STANCE_LABEL, VIOP_STANCE_TONE, viopChips } from '@/lib/bist-viop';

interface ViopNoteProps {
  data: BistViopNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What the VİOP book did today, above the four panels that draw it.
 *
 * The table below can be sorted by any column and still cannot answer the
 * question a reader arrives with, because the answer is a property of the pair:
 * open interest rising means positions were *opened* and falling means they
 * were closed, and only crossing that with the price direction separates new
 * money arriving from somebody being squeezed out. Both print the same green.
 * That crossing is the verdict on the first line.
 *
 * The header is computed in Python and renders whether or not the sentence
 * arrives. That is the point of the split — a model outage costs a paragraph
 * rather than turning a correct panel into one that looks broken, which is also
 * why `AiNote` draws nothing at all rather than an "AI unavailable" notice.
 *
 * Its own component rather than a shared one with the three other board-wide
 * notes, on the reasoning `BistFundsMarketNote` records: the four carry
 * substantially different readings, and a props union wide enough to hold all
 * of them would be harder to read than the duplicated shell.
 *
 * The footer is not decoration. Open interest counts contracts outstanding and
 * every one of them has a long and a short, so a paragraph about "who is
 * positioned" has to say once, in the reader's line of sight, that the exchange
 * publishes size and never sides.
 */
export default function ViopNote({ data, isLoading }: ViopNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;

  // The board could not be read at all. Not the same as a quiet session — and
  // on a scraped source it is far more often the first — so a rendered-but-empty
  // panel would be claiming the second.
  if (!facts) return null;

  const chips = viopChips(facts);

  return (
    <section aria-label="VİOP geneli yapay zekâ okuması" className="surface ai-surface px-4 py-3">
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${VIOP_STANCE_TONE[facts.stance]}`}>
            {VIOP_STANCE_LABEL[facts.stance]}
          </span>

          <span className="text-xs text-fg-subtle">
            {facts.board.contracts} sözleşme · {facts.board.underlyings} dayanak
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

          {facts.stale && <span className="text-2xs text-warn">önbellekten</span>}
        </div>

        <AiNote aiNote={data?.note} />

        {/* Named rather than left implicit. Every reading on this page is a
            size, and a reader who takes a build for evidence of who is buying
            has been misled by a board that was correct throughout. */}
        <p className="text-2xs text-fg-subtle">
          Açık pozisyon yalnızca kapatılmamış sözleşme sayısıdır; her birinin bir uzun bir de kısa
          tarafı var, borsa tarafların kim olduğunu yayımlamıyor. Ölçmedikleri:{' '}
          {facts.not_measured.join(', ')}.
        </p>
      </div>
    </section>
  );
}
