'use client';

import AiNote from '@/components/ui/AiNote';
import type { BistFundsMarketNoteResponse } from '@/lib/bist-api';
import { FUND_STANCE_LABEL, FUND_STANCE_TONE, fundChips } from '@/lib/bist-market-note';

interface BistFundsMarketNoteProps {
  data: BistFundsMarketNoteResponse | undefined;
  isLoading: boolean;
}

/**
 * What one TEFAS fund universe says as a whole, above the screener below it.
 *
 * The table is sorted by return, which puts the winners on top by construction —
 * the one arrangement that cannot show what the typical holder got. So this
 * panel carries the median rather than the leader, the tenth-to-ninetieth
 * percentile spread rather than the top of it, and the count of funds that
 * printed a lira gain their holder did not keep.
 *
 * Its own component rather than a shared one with the equity panel: the two
 * carry substantially different readings, and a props union wide enough to hold
 * both would be harder to read than the duplicated shell. `RegimeCard` and
 * `FlowNote` are split for the same reason.
 *
 * Keyed on the fund type upstream, because Yatırım, Emeklilik and BYF are
 * different universes with different mandates — a median across all three would
 * describe none of them.
 */
export default function BistFundsMarketNote({ data, isLoading }: BistFundsMarketNoteProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  const facts = data?.facts;
  if (!facts) return null;

  const chips = fundChips(facts);
  const windows = facts.deflatable_windows;

  return (
    <section
      aria-label="Fon evreni geneli yapay zekâ okuması"
      className="surface ai-surface px-4 py-3"
    >
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <span className={`text-md font-semibold ${FUND_STANCE_TONE[facts.stance]}`}>
            {FUND_STANCE_LABEL[facts.stance]}
          </span>

          <span className="text-xs text-fg-subtle">
            {facts.fund_type_label} · {facts.measured}/{facts.total} fon ölçüldü
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

        {/* Which windows carry a real return, said once. Without an inflation
            series the whole read is nominal, and a paragraph about purchasing
            power would then be describing a column that does not exist. */}
        <p className="text-2xs text-fg-subtle">
          {windows.length > 0
            ? `Reel getiri yalnızca ${windows.join(', ')} penceresinde hesaplanabiliyor; okuma bu pencereye dayanıyor.`
            : 'Enflasyon serisi alınamadı — bu okumadaki tüm getiriler nominal.'}
        </p>
      </div>
    </section>
  );
}
