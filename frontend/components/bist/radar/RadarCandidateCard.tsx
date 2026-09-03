'use client';

import { useRouter } from 'next/navigation';

import AiNote from '@/components/ui/AiNote';
import type { RadarCandidate } from '@/lib/bist-api';
import {
  EMPTY,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  formatTry,
} from '@/lib/bist-format';
import {
  distanceTo,
  formatRr,
  isWarningFlag,
  scoreTone,
  stanceTone,
  streetText,
  voiceLabel,
} from '@/lib/bist-radar';
import RadarLevelBar from './RadarLevelBar';

/**
 * One name the scan flagged.
 *
 * Reads top to bottom the way the decision was made: the score and why, the
 * trade's shape, the statements behind it, and last the memo — which explains
 * the card and never overrides it. Every figure here was computed on the server
 * and would render exactly the same with the memo missing.
 */
export default function RadarCandidateCard({ candidate }: { candidate: RadarCandidate }) {
  const router = useRouter();
  const { levels, fundamentals } = candidate;
  const street = streetText(candidate);
  const toStop = distanceTo(levels.stop, levels.price);
  const toTarget = distanceTo(levels.target1, levels.price);

  return (
    <article className="surface surface-flat flex flex-col gap-3 p-4">
      <header className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => router.push(`/bist/hisseler/${candidate.ticker}`)}
          className="min-w-0 text-left"
        >
          <span className="block truncate text-base font-semibold text-fg">{candidate.ticker}</span>
          <span className="block truncate text-2xs text-fg-subtle">
            {candidate.name} · {candidate.sector || EMPTY}
          </span>
        </button>
        <div className="flex shrink-0 items-baseline gap-3">
          <Score label="Teknik" value={candidate.score_technical} />
          <Score label="Temel" value={candidate.score_fundamental} />
          <div className="text-right">
            <span className="label block">Toplam</span>
            <span className={`tabnum text-xl font-semibold ${scoreTone(candidate.score_total)}`}>
              {candidate.score_total ?? EMPTY}
            </span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-4 gap-2 text-xs">
        <Fact label="Fiyat" value={formatTry(candidate.price)} />
        <Fact label="Ödül / risk" value={formatRr(levels.rr)} tone="text-fg" />
        <Fact label="Stop'a" value={formatSignedPercent(toStop)} tone="text-down" />
        <Fact label="Hedef 1'e" value={formatSignedPercent(toTarget)} tone="text-up" />
      </div>

      <RadarLevelBar levels={levels} />

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-2xs text-fg-muted sm:grid-cols-4">
        <Fact label="Geri çekilme" value={formatPercent(levels.pullback_pct, 1)} />
        <Fact label="RSI" value={formatNumber(levels.rsi, 0)} />
        <Fact
          label="Hacim"
          value={levels.volume_ratio === null ? EMPTY : `${levels.volume_ratio.toFixed(2)}×`}
          title="Geri çekilme günlerinin hacmi, önceki ayın ortalamasına oranla"
        />
        <Fact
          label="Bant"
          value={
            levels.zone_source === 'support_zone'
              ? `Destek · ${levels.zone_touches} temas`
              : 'Ortalama'
          }
        />
        <Fact
          label="ROE"
          value={formatPercent(fundamentals.roe, 0)}
          title={
            fundamentals.inflation !== null
              ? `Yıllık TÜFE ${formatPercent(fundamentals.inflation, 0)}`
              : undefined
          }
        />
        <Fact label="Reel ciro" value={formatSignedPercent(fundamentals.real_revenue_growth)} />
        <Fact
          label={candidate.sector_class === 'bank' ? 'Reel kâr' : 'Reel FAVÖK'}
          value={formatSignedPercent(fundamentals.real_profit_growth)}
        />
        <Fact
          label="Net borç / FAVÖK"
          value={
            fundamentals.net_debt_ebitda === null
              ? EMPTY
              : formatNumber(fundamentals.net_debt_ebitda, 1)
          }
        />
      </div>

      {(candidate.flags.length > 0 || candidate.adjustments.length > 0 || street) && (
        <div className="flex flex-wrap gap-1.5">
          {candidate.flags.map((flag) => (
            <Chip key={flag.key} tone={isWarningFlag(flag.key) ? 'warn' : 'neutral'}>
              {flag.label}
            </Chip>
          ))}
          {candidate.adjustments.map((adjustment) => (
            <Chip key={adjustment.key} tone={adjustment.points >= 0 ? 'up' : 'down'}>
              {adjustment.label} ({adjustment.points > 0 ? '+' : ''}
              {adjustment.points})
            </Chip>
          ))}
          {street && <Chip tone="neutral">{street}</Chip>}
        </div>
      )}

      {candidate.voices.length > 0 && (
        <div className="border-t border-line pt-3">
          <span className="label mb-1.5 block">Yorumcular ne dedi</span>
          <ul className="flex flex-wrap gap-1.5">
            {candidate.voices.map((v) => (
              <li key={`${v.voice_id}-${v.said_at}-${v.url}`}>
                <a
                  href={v.url}
                  target="_blank"
                  rel="noreferrer"
                  title={v.quote ? `"${v.quote}" — ${v.video_title}` : v.video_title}
                  className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs hover:border-line-strong ${CHIP_TONE[stanceTone(v.stance)]}`}
                >
                  {voiceLabel(v)}
                  <span className="text-fg-subtle">· {v.said_at.slice(5).replace('-', '.')}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {candidate.memo && (
        <div className="border-t border-line pt-3">
          <span className="label mb-1 block">Deneyimli yatırımcı notu</span>
          <AiNote aiNote={candidate.memo} className="whitespace-pre-line" />
        </div>
      )}
    </article>
  );
}

function Score({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="text-right">
      <span className="label block">{label}</span>
      <span className={`tabnum text-sm ${scoreTone(value)}`}>{value ?? EMPTY}</span>
    </div>
  );
}

function Fact({
  label,
  value,
  tone,
  title,
}: {
  label: string;
  value: string;
  tone?: string;
  title?: string;
}) {
  return (
    <div className="flex flex-col" title={title}>
      <span className="label">{label}</span>
      <span className={`tabnum ${tone ?? 'text-fg'}`}>{value}</span>
    </div>
  );
}

const CHIP_TONE: Record<'neutral' | 'warn' | 'up' | 'down', string> = {
  neutral: 'border-line text-fg-muted',
  warn: 'border-warn/40 bg-warn-bg text-fg',
  up: 'border-up/40 text-up',
  down: 'border-down/40 text-down',
};

function Chip({ tone, children }: { tone: keyof typeof CHIP_TONE; children: React.ReactNode }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-2xs ${CHIP_TONE[tone]}`}>{children}</span>
  );
}
