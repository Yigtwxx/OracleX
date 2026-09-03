import { aiNoteText, isGenerating, type AiNote } from '@/lib/ai-note';
import type { BistDisclosureBand } from '@/lib/bist-api';

/**
 * What to say on the KAP tape when the model's read of a filing is not prose.
 *
 * `components/ui/AiNote` draws nothing at all in that case, and everywhere else
 * that is right: the note is a paragraph beside figures the page already
 * renders, so an absent one costs a sentence and reporting an outage the reader
 * cannot act on would make a correct panel look broken.
 *
 * This surface inverts that. The reader pressed a button whose only product is
 * the note, so silence is not a complete page — it is a control that did
 * nothing. Every terminal state therefore has a line, and the lines distinguish
 * the two cases a reader would act on differently: the terminal has no model
 * configured at all, or it has one and it could not be reached this time.
 *
 * Returns null when there is prose to render, which is the caller's signal to
 * draw the note instead.
 */
export function kapNoteMessage(aiNote: AiNote | undefined, isError: boolean): string | null {
  if (isError) return 'Analiz alınamadı. Bildirim KAP akışından düşmüş olabilir.';
  if (aiNoteText(aiNote)) return null;
  if (isGenerating(aiNote) || !aiNote) return 'Bildirim okunuyor…';

  switch (aiNote.reason) {
    case 'ai_disabled':
      return 'Bu terminalde yapay zeka katmanı kapalı, bildirim analizi üretilemiyor.';
    case 'insufficient_data':
      return 'Bildirimde analiz edilecek bir içerik yok; metin ekte olabilir.';
    case 'provider_unavailable':
      return 'Analiz şu anda üretilemedi. Model sağlayıcısına ulaşılamıyor.';
    default:
      // A settled note with nothing in it, and no reason given — including the
      // `ready`-with-an-empty-body case. Naming a cause here would be inventing
      // one, so the line says only what is known and the retry stays offered.
      return 'Bu bildirim için analiz üretilemedi.';
  }
}

/** Whether the failure is one a second press could fix. */
export function kapNoteRetryable(aiNote: AiNote | undefined, isError: boolean): boolean {
  if (isError) return true;
  if (!aiNote || isGenerating(aiNote) || aiNoteText(aiNote)) return false;
  return aiNote.reason !== 'ai_disabled';
}

/**
 * How a filing's band is drawn on the tape.
 *
 * Amber and blue rather than green and red, and that is a correctness choice
 * rather than a palette one. This realm's green and red mean *direction* on
 * every other surface, and a capital increase is neither good news nor bad —
 * drawing one in red would tell a reader the board decided something it
 * explicitly does not decide. Amber says "look here"; blue says "worth a look";
 * neither says which way.
 *
 * `routine` gets no chip at all. It is two rows in three on a live tape, and a
 * chip on two rows in three is a chip on nothing — the label alone, in the
 * meta line's own colour, is what a reader scans past.
 *
 * `unclassified` is dashed on purpose: it has to read as a reading that was not
 * taken, not as the bottom of the scale. The dashes are the only visual
 * vocabulary on this board that means "absent" rather than "low".
 */
export const BAND_CHIP: Record<BistDisclosureBand, string> = {
  high: 'border-warn/40 bg-warn-bg text-warn',
  medium: 'border-accent/30 bg-accent-bg text-accent',
  routine: 'border-transparent text-fg-subtle',
  unclassified: 'border-dashed border-line text-fg-subtle',
};

/** What the chip's tooltip says, so nobody reads the band as a price call. */
export const BAND_TITLE: Record<BistDisclosureBand, string> = {
  high: 'Bildirim türü, şirketin sermayesini, ortaklık yapısını veya kârını değiştiren sınıfta. Fiyat tahmini değil.',
  medium: 'Bildirim türü, sermaye değişmeden takip edilmesi gereken sınıfta. Fiyat tahmini değil.',
  routine: 'Mekanik bildirim: gerçek, ancak şirket haberi değil.',
  unclassified:
    "KAP'ın serbest metin formu — başlığı içeriği hakkında bir şey söylemiyor, bu yüzden tür atanmadı. Analiz butonu tam olarak bu satırlar için var.",
};

/** The top of the backend's scale. Mirrors `MAX_SCORE` in `kap_materiality`. */
export const MAX_SCORE = 10;

/**
 * How far the bar fills, as a percentage of one shared track.
 *
 * A length rather than a colour alone, because colour alone is not a reading a
 * reader can rank. Two amber chips beside each other say "both of these are the
 * loud kind"; two bars say which one is louder, and they say it to someone who
 * cannot tell amber from blue. Every track on the tape is the same width, so
 * the comparison holds down the whole column.
 *
 * The score itself is never printed. Ten stops make the bar worth scanning, and
 * a "9/10" beside a company announcement would claim a precision nobody
 * measured — the reader would take it for a scored call on the filing rather
 * than for the ordering it is. The length ranks; the tooltip says the level in
 * words; the digit stays out of the page.
 *
 * A missing score fills nothing, and the component draws its track dashed:
 * the absence of a reading, not the bottom of the scale.
 */
export function scoreFillPct(score: number | null): number {
  if (score === null || !Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, (score / MAX_SCORE) * 100));
}

/**
 * The colour ramp, and why it is this one.
 *
 * Amber, blue, slate — never green and red. Those two mean *direction* on every
 * other surface of this realm, and importance has no direction: a capital
 * increase is neither good news nor bad, so painting one red would report a
 * judgement the board explicitly does not make. The ramp reads as
 * loud → worth a look → background, which is the axis it is actually measuring.
 */
export const BAND_FILL: Record<BistDisclosureBand, string> = {
  high: 'bg-warn',
  medium: 'bg-accent',
  routine: 'bg-fg-subtle',
  unclassified: '',
};

/** The level in words, for the reader who is not looking at the bar. */
export const BAND_LEVEL_LABEL: Record<BistDisclosureBand, string> = {
  high: 'Önem: yüksek',
  medium: 'Önem: orta',
  routine: 'Önem: rutin',
  unclassified: 'Önem: belirlenemedi',
};
