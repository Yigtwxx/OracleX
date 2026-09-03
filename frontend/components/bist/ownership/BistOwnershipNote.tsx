'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistOwnershipNoteResponse } from '@/lib/bist-api';
import { formatDate } from '@/lib/bist-format';
import {
  OWNERSHIP_STANCE_LABEL,
  OWNERSHIP_STANCE_TONE,
  ownershipChips,
} from '@/lib/bist-ownership';

interface BistOwnershipNoteProps {
  data: BistOwnershipNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What the whole ownership board says, above the cards that draw it.
 *
 * Every card answers "what does this holder own"; the reader's question sits
 * above them — how much of the index is the state, how much is family
 * holdings, how much can actually trade. The stance and the chips are
 * computed in Python from the same facts the paragraph was written from, so
 * a cached paragraph can never disagree with the figures beside it.
 *
 * The footer is not decoration: there is no 13F here, and a paragraph about
 * who holds the index has to say once, in the reader's line of sight, that it
 * sees stakes above 5% and nothing beneath them.
 */
export default function BistOwnershipNote({ data, isLoading }: BistOwnershipNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;
  if (!facts) return null;

  return (
    <section
      aria-label="Ortaklık geneli yapay zekâ okuması"
      className="surface ai-surface px-4 py-3"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${OWNERSHIP_STANCE_TONE[facts.stance]}`}>
            {OWNERSHIP_STANCE_LABEL[facts.stance]}
          </span>

          <span className="text-xs text-fg-subtle">
            {facts.coverage.entities_with_data} ortak · {facts.coverage.tickers_covered}/
            {facts.coverage.tickers_total} {facts.coverage.universe} kartı
          </span>

          {ownershipChips(facts).map((chip) => (
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
          Bu okuma yalnızca %5 üzeri pay tablolarına ve okunabilen {facts.funds.readable}/
          {facts.funds.tracked} fon raporuna dayanıyor; değerler pay oranı × günün piyasa değeridir.
          Pay değişimleri {formatDate(facts.coverage.tracking_since)} tarihinden beri günlük kart
          karşılaştırmasıyla izleniyor; daha eski giriş ve çıkışlar bilinmiyor.
        </p>
      </div>
    </section>
  );
}
