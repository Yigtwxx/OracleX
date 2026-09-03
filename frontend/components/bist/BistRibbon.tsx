'use client';

import Link from 'next/link';

import type { BistDominance, BistSentiment, BistSentimentHorizon } from '@/lib/bist-api';
import { formatPercent } from '@/lib/bist-format';

/**
 * The board-wide readings, on one line under the page title.
 *
 * The same shape `components/home/MarketRibbon.tsx` gives the crypto realm, and
 * for the same reason: these are context for everything below, so they should
 * cost a glance rather than a panel. A reader who has learned that a small
 * filled track means "share of something" on Home should not have to relearn it
 * here.
 *
 * What differs is what there is to show. Crypto has three dominances published
 * as such; Borsa İstanbul has none, so the equivalent is derived — the largest
 * sector's share of capitalisation, which is structural, and the session's own
 * turnover concentration, which is not. Both come from the same equity board
 * the panels below are drawn from, which is what makes the index checkable
 * rather than asserted.
 */

/** Ribbon-width names for components whose API labels are full sentences. */
const SHORT_LABEL: Record<string, string> = {
  breadth: 'Genişlik',
  limit: 'Tavan/taban',
  flow: 'Para akışı',
  breadth_1w: 'Hafta',
  breadth_1m: 'Ay',
  above_sma50: 'SMA50 üstü',
  momentum: 'Momentum',
  range: 'Yıllık konum',
  above_sma200: 'SMA200 üstü',
};

/**
 * The horizons in the order the index weighs them, fastest first. Each takes
 * an equal third of the score; the ribbon groups by them so a reader can see
 * which third is doing the talking when the session and the trend disagree.
 */
const HORIZONS: { code: BistSentimentHorizon; label: string }[] = [
  { code: 'session', label: 'Seans' },
  { code: 'trend', label: 'Trend' },
  { code: 'year', label: 'Yıl' },
];

/**
 * The index's own ramp, matching `getFearGreedColor` on the crypto side.
 *
 * Three steps rather than a gradient: the bands the score is labelled with are
 * discrete, and a continuously interpolated hue would imply a precision the
 * five equally-weighted components do not have.
 */
export function moodColor(score: number): string {
  if (score <= 44) return 'var(--down)';
  if (score <= 55) return 'var(--warn)';
  return 'var(--up)';
}

export function Stat({
  label,
  title,
  children,
}: {
  label: string;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1.5" title={title}>
      <span className="label">{label}</span>
      {children}
    </span>
  );
}

export function Divider() {
  return <span className="h-3 w-px bg-line" aria-hidden />;
}

/** A share of something, as a length. `percent` is 0–100. */
export function Track({ percent, color }: { percent: number; color: string }) {
  return (
    <span className="h-1 w-8 overflow-hidden rounded-full bg-line" aria-hidden>
      <span
        className="block h-full rounded-full"
        style={{
          width: `${Math.min(100, Math.max(0, percent))}%`,
          backgroundColor: color,
        }}
      />
    </span>
  );
}

/**
 * The equity fear & greed reading.
 *
 * Its own component because it is the one thing on this ribbon that is not
 * about equities specifically — it is the mood of the market the funds are
 * invested in too, so the fund board shows the same score rather than a
 * second, differently-computed one.
 *
 * Spelled out rather than initialled, as on the crypto ribbon: an acronym is
 * the one thing on this line that cannot be worked out from what is beside it.
 */
export function FearGreedStat({ sentiment }: { sentiment: BistSentiment }) {
  return (
    <Stat label="Korku ve açgözlülük" title={`${sentiment.measured} hisseden hesaplandı`}>
      <span
        className="tabnum font-mono font-semibold"
        style={{ color: moodColor(sentiment.score) }}
      >
        {sentiment.score}
      </span>
      <span className="text-fg-subtle">{sentiment.label}</span>
      <Track percent={sentiment.score} color={moodColor(sentiment.score)} />
    </Stat>
  );
}

export default function BistRibbon({
  sentiment,
  dominance,
}: {
  sentiment: BistSentiment | null;
  dominance: BistDominance;
}) {
  const sectorWeight = (dominance.sector_weight ?? 0) * 100;
  const topShare = (dominance.top_turnover_share ?? 0) * 100;
  const top5Share = (dominance.top5_turnover_share ?? 0) * 100;

  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-2xs">
      {sentiment ? (
        <>
          <FearGreedStat sentiment={sentiment} />

          <Divider />

          {/* What the score was reached from, grouped by horizon. The title
              carries the figure each component was scored on and its share of
              the composite, so the index can be checked rather than taken on
              trust. */}
          {HORIZONS.map(({ code, label }) => {
            const members = sentiment.components.filter((c) => c.horizon === code);
            if (members.length === 0) return null;
            return (
              <span key={code} className="flex items-center gap-x-2.5">
                <span className="label text-fg-subtle">{label}</span>
                {members.map((component) => (
                  <Stat
                    key={component.key}
                    label={SHORT_LABEL[component.key] ?? component.label}
                    title={`${component.label}: ${component.reading} · endeksin %${Math.round(component.weight * 100)}'i`}
                  >
                    <span className="tabnum font-mono text-fg">{Math.round(component.score)}</span>
                    <Track percent={component.score} color={moodColor(component.score)} />
                  </Stat>
                ))}
              </span>
            );
          })}
        </>
      ) : (
        // Refused rather than defaulted to fifty. A placeholder on a sentiment
        // gauge is a reading someone would act on.
        <span className="text-fg-subtle">Duyarlılık endeksi için yeterli ölçüm yok</span>
      )}

      {dominance.sector && (
        <>
          <Divider />
          <Stat label={dominance.sector} title="Piyasa değerinin payı">
            <span className="tabnum font-mono text-fg">
              {formatPercent(dominance.sector_weight)}
            </span>
            <Track percent={sectorWeight} color="var(--accent)" />
          </Stat>
        </>
      )}

      {dominance.top_ticker && (
        <>
          <Divider />
          <Stat label="Ciro" title="Günün işlem hacminde tek hissenin payı">
            <Link
              href={`/bist/hisseler/${dominance.top_ticker}`}
              className="font-mono text-fg hover:underline"
            >
              {dominance.top_ticker}
            </Link>
            <span className="tabnum font-mono text-fg">
              {formatPercent(dominance.top_turnover_share)}
            </span>
            <Track percent={topShare} color="var(--nav-bist-smart-money)" />
          </Stat>
          <Stat label="İlk 5" title="Günün işlem hacminde ilk beş hissenin payı">
            <span className="tabnum font-mono text-fg">
              {formatPercent(dominance.top5_turnover_share)}
            </span>
            <Track percent={top5Share} color="var(--nav-bist-smart-money)" />
          </Stat>
        </>
      )}
    </div>
  );
}
