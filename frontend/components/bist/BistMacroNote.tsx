'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistMacroNoteResponse } from '@/lib/bist-api';
import { MACRO_STANCE_LABEL, MACRO_STANCE_TONE, macroChips } from '@/lib/bist-market-note';

interface BistMacroNoteProps {
  data: BistMacroNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What the backdrop says as a whole, above the tiles that print its parts.
 *
 * Six tiles print six figures and the reading sits between them: the rate
 * against inflation, the rate against the lira's loss, producer prices against
 * consumer prices. The header carries those crossings from figures computed in
 * Python — Fisher's real rate among them, which is the one a reader does wrong
 * in their head — and the sentence beneath says what they mean together, when
 * the model answers.
 *
 * The header renders whether or not the sentence arrives, which is the point
 * of the split. Its own component rather than a shared one, on the reasoning
 * `BistFundsMarketNote` records: the reads differ too much for a props union
 * to be clearer than the duplicated shell.
 *
 * The footer names what this board does not measure. A backdrop read without
 * the CDS spread or the reserves can be right about what it sees and still
 * miss the day's driver, and the reader is entitled to know which instruments
 * were on the desk.
 */
export default function BistMacroNote({ data, isLoading }: BistMacroNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;

  // The two figures every other reading hangs off could not be read. The
  // tiles below say so in their own way; a panel here would claim a backdrop.
  if (!facts) return null;

  const chips = macroChips(facts);

  return (
    <section aria-label="Makro geneli yapay zekâ okuması" className="surface ai-surface px-4 py-3">
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${MACRO_STANCE_TONE[facts.stance]}`}>
            {MACRO_STANCE_LABEL[facts.stance]}
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

        <p className="text-2xs text-fg-subtle">
          Reel faiz Fisher ilişkisiyle hesaplanır, çıkarmayla değil; kur karşılaştırması gösterge
          niteliğindedir, gerçekleşmiş getiri değildir. Ölçmedikleri:{' '}
          {facts.not_measured.join(', ')}.
        </p>
      </div>
    </section>
  );
}
