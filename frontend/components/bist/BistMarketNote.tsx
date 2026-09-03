'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistMarketNoteResponse } from '@/lib/bist-api';
import { MARKET_STANCE_LABEL, MARKET_STANCE_TONE, marketChips } from '@/lib/bist-market-note';

interface BistMarketNoteProps {
  data: BistMarketNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What the equity board says as a whole, above the screener that lists its rows.
 *
 * The table below can be sorted by any column and still cannot answer the
 * question a reader arrives with, because the answer is a property of the set:
 * an index carried up while most listings fell is a different market from one
 * the whole board took part in, and the headline figure is identical in both.
 * That comparison is the verdict on the first line.
 *
 * The header is computed in Python and renders whether or not the sentence
 * arrives. That is the point of the split — a model outage costs a paragraph
 * rather than turning a correct panel into one that looks broken, which is also
 * why `AiNote` draws nothing at all rather than an "AI unavailable" notice.
 *
 * It sits under the fear & greed ribbon rather than inside it because the ribbon
 * is a line of readings to glance at and this is a claim to read. Putting it
 * below the stale strip keeps a staleness warning next to the table it is about.
 */
export default function BistMarketNote({ data, isLoading }: BistMarketNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;

  // The board could not be read at all. Not the same as a quiet market, and a
  // rendered-but-empty panel would be claiming the second.
  if (!facts) return null;

  const chips = marketChips(facts);

  return (
    <section aria-label="Piyasa geneli yapay zekâ okuması" className="surface ai-surface px-4 py-3">
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${MARKET_STANCE_TONE[facts.stance]}`}>
            {MARKET_STANCE_LABEL[facts.stance]}
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

        {/* Named rather than left implicit. A call made from breadth, valuation
            and one macro print can be right about everything in front of it and
            still miss the day's actual driver, and the reader is entitled to
            know which instruments were never on the desk. */}
        <p className="text-2xs text-fg-subtle">Ölçmedikleri: {facts.not_measured.join(', ')}.</p>
      </div>
    </section>
  );
}
