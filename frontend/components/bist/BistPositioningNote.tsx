'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistPositioningNoteResponse } from '@/lib/bist-api';
import {
  POSITIONING_STANCE_LABEL,
  POSITIONING_STANCE_TONE,
  positioningChips,
} from '@/lib/bist-market-note';

interface BistPositioningNoteProps {
  data: BistPositioningNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What the whole positioning board says, above the four panels that draw it.
 *
 * Each panel answers its own question correctly and the reader's question sits
 * between them: the scatter knows which names are busy, the histogram knows
 * where the board sits in its own year, and nothing on the page crosses the two.
 * So this panel carries the crossing — the crowd's median position in its year
 * against the board's, the float that crowding is happening in, and how much of
 * the board's whole score sits in one sector.
 *
 * Its own component rather than a shared one with the two market notes, on the
 * reasoning `BistFundsMarketNote` records: the three carry substantially
 * different readings, and a props union wide enough to hold all of them would be
 * harder to read than the duplicated shell.
 *
 * The footer is not decoration. This board was specified as a fund-to-stock
 * cross index and no public source carries the holdings it needs, so a paragraph
 * about where the crowd is leaning has to say once, in the reader's line of
 * sight, that it is reading published float and volume rather than anyone's
 * portfolio.
 */
export default function BistPositioningNote({ data, isLoading }: BistPositioningNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;
  if (!facts) return null;

  const chips = positioningChips(facts);

  return (
    <section
      aria-label="Konumlanma geneli yapay zekâ okuması"
      className="surface ai-surface px-4 py-3"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${POSITIONING_STANCE_TONE[facts.stance]}`}>
            {POSITIONING_STANCE_LABEL[facts.stance]}
          </span>

          <span className="text-xs text-fg-subtle">
            en kalabalık {facts.crowd.cohort} isim · {facts.board.total} hisse tarandı
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
          Bu okuma yalnızca yayımlanan büyüklüklere dayanıyor
          {facts.futures === null && ' — VİOP açık pozisyonu bugün alınamadı'}; fonların hangi
          hisseyi tuttuğu hiçbir kamuya açık uçtan alınamadığı için burada yer almıyor.
        </p>
      </div>
    </section>
  );
}
