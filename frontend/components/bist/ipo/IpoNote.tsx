'use client';

import AiNote from '@/components/ui/AiNote';
import type { AiNote as AiNoteShape } from '@/lib/ai-note';
import type { IpoBoard } from '@/lib/bist-api';
import { formatPercent, formatSignedPercent } from '@/lib/bist-format';
import { type IpoBasis, medianReturn, positiveShare } from '@/lib/bist-ipo';

/**
 * The model's read, above the board.
 *
 * The chips are computed here: the counts and the median are arithmetic the
 * page already did, and a model asked to restate them is a model given three
 * chances to get them wrong.
 */
export default function IpoNote({
  board,
  basis,
  note,
  isLoading,
}: {
  board: IpoBoard | undefined;
  basis: IpoBasis;
  note: AiNoteShape | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <div className="surface shimmer h-[92px]" />;
  if (!board) return null;

  const median = medianReturn(board.past, basis);
  const positive = positiveShare(board.past, basis);

  const chips = [
    { text: `${board.upcoming.length} yaklaşan`, title: 'Önümüzdeki pencerede ilan edilmiş arz.' },
    {
      text: `${board.coverage.returns_measured} ölçülen arz`,
      title: `${board.coverage.returns_unmeasured} arzın getirisi ölçülemedi ve hiçbir toplulaştırmaya girmedi.`,
    },
    {
      text: `Medyan ${formatSignedPercent(median, 0)}`,
      title: basis === 'real' ? 'TÜFE arındırılmış.' : 'Nominal, enflasyon arındırılmadan.',
    },
    {
      text: `Pozitif ${formatPercent(positive, 0)}`,
      title: 'Arz fiyatının üstünde işlem gören arzların oranı.',
    },
  ];

  return (
    <section
      aria-label="Halka arz yapay zekâ okuması"
      className="surface ai-surface space-y-2 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {chips.map((chip) => (
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
        Ölçmedikleri: takvim halkarz.com&apos;dan geliyor — topluluk tarafından tutulan üçüncü taraf
        bir site, KAP veya SPK değil. Getiriler kesinleşen arz fiyatına göre ölçülüyor ve tahsisatı
        yok sayıyor; kimse fiilen o fiyattan tam lot almadı. Getirisi ölçülemeyen arzlar yukarıdaki
        hiçbir rakama dahil değil.
      </p>
    </section>
  );
}
