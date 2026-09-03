/**
 * Derivations for the Radar page — the branches, kept out of the components
 * because this repo tests `lib/*.ts` and not components.
 *
 * Every number the page draws is computed on the server; what lives here is
 * how those numbers turn into a bar position, a tone or a sentence, and the
 * handful of places where "no answer" must not render as zero.
 */

import type { RadarCandidate, RadarLevels, RadarResult, RadarRow, RadarVoice } from './bist-api';

/** Tailwind tone for a 0–100 score. */
export function scoreTone(score: number | null | undefined): string {
  if (score === null || score === undefined) return 'text-fg-subtle';
  if (score >= 75) return 'text-up';
  if (score >= 60) return 'text-fg';
  return 'text-fg-muted';
}

/** `2.4×`, or the dash. */
export function formatRr(rr: number | null | undefined): string {
  if (rr === null || rr === undefined || !Number.isFinite(rr)) return '—';
  return `${rr.toFixed(1)}×`;
}

export interface LevelMarks {
  /** 0..1 positions on a bar that runs from the stop to the highest target. */
  stop: number;
  entryLow: number;
  entryHigh: number;
  price: number;
  target1: number;
  target2: number | null;
}

/**
 * Where each level sits on one horizontal bar, stop at the left edge and the
 * furthest target at the right.
 *
 * Returns null when the levels do not span a range — a stop at or above the
 * target — because a bar with every mark at one end is a picture of nothing.
 */
export function levelMarks(levels: RadarLevels): LevelMarks | null {
  const low = levels.stop;
  const high = Math.max(levels.target1, levels.target2 ?? levels.target1);
  if (!(high > low)) return null;
  const at = (value: number) => Math.max(0, Math.min(1, (value - low) / (high - low)));
  return {
    stop: 0,
    entryLow: at(levels.entry_low),
    entryHigh: at(levels.entry_high),
    price: at(levels.price),
    target1: at(levels.target1),
    target2: levels.target2 === null ? null : at(levels.target2),
  };
}

/** Signed distance from price to a level, as a fraction; null without a price. */
export function distanceTo(level: number | null, price: number | null): number | null {
  if (level === null || price === null || !price) return null;
  return level / price - 1;
}

/**
 * The one-line reason a row is not a candidate, in Turkish.
 *
 * A vetoed row names its first veto rather than "Temel veto", because the veto
 * is the fact the reader came to the table for.
 */
export function rejectionText(row: RadarRow): string {
  if (row.stage_reached === 'candidate') return 'Aday';
  if (row.vetoes.length) return row.vetoes[0].label;
  return row.rejected_label ?? row.rejected_reason ?? '—';
}

export const STAGE_LABEL: Record<RadarRow['stage_reached'], string> = {
  gate: 'Trend filtresi',
  technical: 'Teknik',
  scored: 'Puanlandı',
  candidate: 'Aday',
};

/** `Bugün kurulum yok` is a result, and this is how the header says so. */
export function summaryLine(result: RadarResult): string {
  const n = result.candidates.length;
  if (n === 0) return `${result.universe_size} hisse tarandı, bugün kurulum yok.`;
  return `${result.universe_size} hisse tarandı, ${n} aday.`;
}

/** Whether the memos are still being written for a result the page already shows. */
export function memosPending(result: RadarResult | undefined): boolean {
  if (!result) return false;
  return result.memos.total > 0 && result.memos.done < result.memos.total;
}

/** The Turkish sentence for how deep the statements went. */
export function depthNote(result: RadarResult): string | null {
  if (result.fundamental_depth === 'full') return null;
  if (result.fundamental_depth === 'partial') {
    return `Mali tablolar ${result.fundamentals_covered}/${result.universe_size} şirket için okunabildi; kalanlar yalnızca çarpanlarla puanlandı.`;
  }
  return 'Mali tablolar alınamadı — temel puan yalnızca çarpanlara dayanıyor, bilanço doğrulanmadı.';
}

/** Which flags are cautions rather than confirmations. */
export function isWarningFlag(key: string): boolean {
  return [
    'earnings_soon',
    'heavy_volume',
    'ratios_only',
    'kap_unchecked',
    'no_fundamentals',
  ].includes(key);
}

/** Street gap as a signed percent string with the analyst count, or null without coverage. */
export function streetText(candidate: RadarCandidate): string | null {
  const street = candidate.street;
  if (!street) return null;
  const pct = (street.gap_pct * 100).toFixed(0);
  const sign = street.gap_pct > 0 ? '+' : '';
  return `${street.analysts} analist · hedef ${sign}${pct}%`;
}

export const STANCE_LABEL: Record<RadarVoice['stance'], string> = {
  bullish: 'Yükseliş',
  bearish: 'Düşüş',
  neutral: 'Nötr',
};

/**
 * `Tuncay Turşucu · Yükseliş · isabet %62 (n=13)`, or with `erken` when the
 * record is too short to mean anything.
 *
 * The accuracy shown is the shrunk one: a commentator with one graded call reads
 * 60%, never 100%, and a sample under ten is labelled rather than trusted.
 */
export function voiceLabel(voice: RadarVoice): string {
  const stance = STANCE_LABEL[voice.stance] ?? voice.stance;
  const acc = voice.accuracy;
  if (!acc || acc.n === 0) return `${voice.voice_name} · ${stance} · henüz notlanmadı`;
  const pct = Math.round(acc.shrunk * 100);
  const early = acc.n < 10 ? ', erken' : '';
  return `${voice.voice_name} · ${stance} · isabet %${pct} (n=${acc.n}${early})`;
}

/** Chip tone for a stance. */
export function stanceTone(stance: RadarVoice['stance']): 'up' | 'down' | 'neutral' {
  if (stance === 'bullish') return 'up';
  if (stance === 'bearish') return 'down';
  return 'neutral';
}

/** The one-line footer for the commentator step, or null when it ran cleanly. */
export function voicesNote(result: RadarResult): string | null {
  const report = result.voices_report;
  if (!report) return null;
  if (!report.checked) return 'Yorumcu kontrolü bu taramada yapılamadı.';
  if (report.failures.length)
    return `Yorumcu kaynaklarından ${report.failures.length} tanesi okunamadı.`;
  return null;
}
