'use client';

import { useState } from 'react';
import { useStore } from '@/store/useStore';
import { useNewsAnalysis, useNewsAnalysisJob } from '@/hooks/queries';
import StageChecklist from '@/components/analysis/StageChecklist';
import TechnicalPanel from '@/components/analysis/TechnicalPanel';
import {
  Activity,
  AlertTriangle,
  Brain,
  ChevronDown,
  ExternalLink,
  FileText,
  Gauge,
  History,
  Minus,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import type { EvidenceItem, NewsAnalysis, PrecedentAnalogy } from '@/lib/api';

type Sentiment = 'bullish' | 'bearish' | 'neutral';

const SENTIMENT_STYLE: Record<Sentiment, { text: string; bg: string; border: string }> = {
  bullish: { text: 'text-up', bg: 'bg-up-bg', border: 'border-up' },
  bearish: { text: 'text-down', bg: 'bg-down-bg', border: 'border-down' },
  neutral: { text: 'text-warn', bg: 'bg-warn-bg', border: 'border-warn' },
};

/**
 * How much weight the item itself carries, before any judgement about
 * direction. A routine item is the common case, not a failure to analyse.
 */
const MATERIALITY_STYLE: Record<string, string> = {
  extraordinary: 'bg-down-bg text-down',
  significant: 'bg-warn-bg text-warn',
  routine: 'bg-surface-2 text-fg-muted',
  noise: 'bg-surface-2 text-fg-subtle',
};

const HORIZON_LABELS: Record<string, string> = {
  immediate: 'Immediate (minutes to hours)',
  'short-term': 'Short term (1–7 days)',
  'medium-term': 'Medium term (1–4 weeks)',
  'long-term': 'Long term (1+ months)',
};

function sentimentIcon(sentiment: string) {
  if (sentiment === 'bullish') return <TrendingUp className="w-4 h-4" />;
  if (sentiment === 'bearish') return <TrendingDown className="w-4 h-4" />;
  return <Minus className="w-4 h-4" />;
}

function directionClass(direction: string): string {
  if (direction === 'bullish') return 'bg-up-bg text-up';
  if (direction === 'bearish') return 'bg-down-bg text-down';
  return 'bg-surface-2 text-fg-muted';
}

function formatPct(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function Section({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: typeof Target;
  children: React.ReactNode;
}) {
  return (
    <div className="surface p-4">
      <div className="flex items-center gap-2 mb-2.5">
        <Icon className="w-3.5 h-3.5 text-fg-muted" />
        <h4 className="label">{title}</h4>
      </div>
      {children}
    </div>
  );
}

/** One claim behind the verdict, expandable to the line that supports it. */
function EvidenceRow({ item }: { item: EvidenceItem }) {
  const [open, setOpen] = useState(false);
  const hasQuote = !!item.quote;

  return (
    <div className="py-2 first:pt-0 last:pb-0">
      <div className="flex items-start gap-2">
        <span
          className={`shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-2xs font-semibold uppercase ${directionClass(
            item.direction
          )}`}
        >
          {item.direction}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-base text-fg-muted leading-relaxed">{item.claim}</p>
          {hasQuote && (
            <button
              onClick={() => setOpen((v) => !v)}
              className="flex items-center gap-1 mt-1 text-sm text-fg-subtle hover:text-fg transition-colors"
              aria-expanded={open}
            >
              <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
              {open ? 'Hide source line' : 'Show source line'}
            </button>
          )}
          {hasQuote && open && (
            <blockquote className="mt-1.5 pl-2.5 border-l-2 border-line text-sm text-fg-subtle italic leading-relaxed">
              “{item.quote}”
            </blockquote>
          )}
        </div>
        {item.weight === 'primary' && (
          <span className="shrink-0 mt-0.5 text-2xs text-fg-subtle uppercase tracking-wide">
            key
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * A past event this item resembles.
 *
 * The `surprised` badge is the reason this section exists: an approval followed
 * by a lower price, or a lawsuit followed by a higher one, is the most useful
 * thing retrieval can surface — and it used to reach only the model.
 */
function PrecedentCard({ precedent }: { precedent: PrecedentAnalogy }) {
  const horizons = Object.entries(precedent.horizons)
    .map(([days, pct]) => [Number(days), pct] as const)
    .filter(([days]) => !Number.isNaN(days))
    .sort((a, b) => a[0] - b[0]);

  return (
    <div className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-2">
        <p className="text-base text-fg leading-snug">{precedent.title}</p>
        <span className="shrink-0 text-sm text-fg-subtle tabnum font-mono">
          {Math.round(precedent.similarity * 100)}%
        </span>
      </div>

      <p className="text-sm text-fg-subtle mt-0.5">
        {[precedent.date, precedent.symbol].filter(Boolean).join(' · ') || 'date unknown'}
      </p>

      {horizons.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1.5">
          {horizons.map(([days, pct]) => (
            <span
              key={days}
              className={`px-1.5 py-0.5 rounded text-sm font-mono tabnum ${
                pct >= 0 ? 'bg-up-bg text-up' : 'bg-down-bg text-down'
              }`}
            >
              {days}d {formatPct(pct)}
            </span>
          ))}
        </div>
      )}

      {precedent.surprised && (
        <p className="mt-1.5 text-sm text-warn leading-relaxed">
          The market did the opposite of what the headline implied
          {precedent.apparentSentiment && precedent.durableDirection
            ? ` — read as ${precedent.apparentSentiment}, settled ${precedent.durableDirection}.`
            : '.'}
        </p>
      )}
    </div>
  );
}

export default function OraclePanel() {
  const { selectedNews, analysisJobIds } = useStore();
  const newsId = selectedNews?.id;

  const jobId = newsId ? analysisJobIds[newsId] : undefined;
  const { data: job } = useNewsAnalysisJob(jobId);
  // Keyed by news id, so a late response for a previously selected item cannot
  // render here. This is the race fix — not a guard, a shape.
  const { data: analysis } = useNewsAnalysis(newsId);

  const sentiment = (analysis?.sentiment ?? 'neutral') as Sentiment;
  const style = SENTIMENT_STYLE[sentiment] ?? SENTIMENT_STYLE.neutral;

  const jobFailed = job?.status === 'error';
  const running = job?.status === 'queued' || job?.status === 'running';
  // The verdict is shown as soon as it exists, even while a later stage is
  // still auditing it.
  const auditing = running && !!analysis;

  return (
    <div className="flex flex-col h-full">
      <div className="h-10 shrink-0 px-4 border-b border-line flex items-center gap-2 bg-surface">
        <Brain className="w-3.5 h-3.5 text-fg-muted" />
        <h2 className="text-base font-semibold text-fg">Oracle</h2>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-3">
        {!selectedNews ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6">
            <Brain className="w-6 h-6 text-fg-subtle mb-3" />
            <h3 className="text-md text-fg-muted mb-1.5">Select a news item</h3>
            <p className="text-base text-fg-subtle leading-relaxed">
              Click any article in the Feed to get a research note: what the source actually says,
              the mechanism, the market backdrop and what happened after similar events.
            </p>
          </div>
        ) : jobFailed && !analysis ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6">
            <AlertTriangle className="w-6 h-6 text-down mb-3" />
            <h3 className="text-md text-fg mb-1.5">Analysis failed</h3>
            <p className="text-sm text-fg-subtle font-mono leading-relaxed break-words">
              {job?.error}
            </p>
          </div>
        ) : analysis ? (
          <AnalysisBody
            analysis={analysis}
            title={selectedNews.title}
            style={style}
            auditing={auditing}
          />
        ) : (
          /* Selected but nothing to show yet: the cached note is being read, the
             job is being started, or it is running. All three are the same thing
             to the reader — work in progress — and collapsing them avoids a
             blank panel in the gap between the click and the first job poll. */
          <div className="space-y-3">
            <div className="surface p-3">
              <p className="label mb-1">Analysing</p>
              <p className="text-base text-fg line-clamp-2">{selectedNews.title}</p>
            </div>
            {job?.stages?.length ? (
              <StageChecklist
                stages={job.stages}
                stageIndex={job.stageIndex}
                elapsedSeconds={job.elapsedSeconds}
                dense
              />
            ) : (
              <p className="px-2 text-base text-fg-subtle">Starting analysis…</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function AnalysisBody({
  analysis,
  title,
  style,
  auditing,
}: {
  analysis: NewsAnalysis;
  title: string;
  style: { text: string; bg: string; border: string };
  auditing: boolean;
}) {
  const materialityClass =
    MATERIALITY_STYLE[analysis.materiality ?? ''] ?? 'bg-surface-2 text-fg-muted';
  const technical = analysis.technical_signals;

  return (
    <div className="space-y-3">
      <div className="surface p-3">
        <p className="label mb-1">Analysing</p>
        <p className="text-base text-fg line-clamp-2">{title}</p>
      </div>

      {/* Verdict */}
      <div className={`p-3 rounded-lg border ${style.bg} ${style.border}`}>
        <div className="flex items-center justify-between gap-3">
          <div className={`flex items-center gap-2 ${style.text}`}>
            {sentimentIcon(analysis.sentiment)}
            <span className="text-md font-semibold capitalize">{analysis.sentiment}</span>
          </div>
          <span className={`text-base font-mono tabnum ${style.text}`}>
            {Math.round(analysis.confidence * 100)}% confidence
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 mt-2">
          {analysis.materiality && (
            <span
              className={`px-1.5 py-0.5 rounded text-2xs font-semibold uppercase ${materialityClass}`}
            >
              {analysis.materiality}
            </span>
          )}
          {analysis.timeHorizon && (
            <span className="px-1.5 py-0.5 rounded bg-surface-2 text-fg-muted text-2xs">
              {HORIZON_LABELS[analysis.timeHorizon] ?? analysis.timeHorizon}
            </span>
          )}
          {auditing && (
            <span className="px-1.5 py-0.5 rounded bg-surface-2 text-fg-subtle text-2xs">
              auditing…
            </span>
          )}
        </div>

        {/* No model was reachable, so this verdict is a keyword count over the
            headline — say so rather than letting it read as analysis. */}
        {analysis.source === 'keyword-fallback' && (
          <p className="mt-2 pt-2 border-t border-line text-sm text-fg-subtle">
            Keyword fallback — no AI provider was reachable
          </p>
        )}
      </div>

      {analysis.mechanism && (
        <Section title="Mechanism" icon={Target}>
          <p className="text-base text-fg leading-relaxed">{analysis.mechanism}</p>
        </Section>
      )}

      <Section title="Analysis" icon={FileText}>
        <p className="text-base text-fg-muted leading-relaxed">{analysis.reasoning}</p>
      </Section>

      {analysis.evidence.length > 0 && (
        <Section title="Evidence" icon={FileText}>
          <div className="divide-y divide-line">
            {analysis.evidence.map((item, i) => (
              <EvidenceRow key={i} item={item} />
            ))}
          </div>
        </Section>
      )}

      {analysis.regimeNote && (
        <Section title="Market Backdrop" icon={Gauge}>
          <p className="text-base text-fg-muted leading-relaxed">{analysis.regimeNote}</p>
        </Section>
      )}

      {analysis.precedents.length > 0 && (
        <Section title="Precedent" icon={History}>
          <div className="divide-y divide-line">
            {analysis.precedents.slice(0, 3).map((precedent, i) => (
              <PrecedentCard key={i} precedent={precedent} />
            ))}
          </div>
        </Section>
      )}

      {analysis.invalidation && (
        <Section title="What would make this wrong" icon={ShieldAlert}>
          <p className="text-base text-fg-muted leading-relaxed">{analysis.invalidation}</p>
        </Section>
      )}

      {technical && (
        <Section title="Technical Analysis" icon={Activity}>
          <TechnicalPanel technical={technical} />
        </Section>
      )}

      {analysis.citations.length > 0 && (
        <Section title="Sources" icon={ExternalLink}>
          <ul className="space-y-1.5">
            {analysis.citations.map((citation, i) => (
              <li key={i}>
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-start gap-1.5 text-base text-accent hover:underline"
                >
                  <ExternalLink className="w-3 h-3 shrink-0 mt-1" />
                  <span className="min-w-0 break-words">{citation.label}</span>
                </a>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Always rendered: a verdict built on a headline alone must not look
          like one built on the full article and four feeds. */}
      <div className="px-1 pb-1 text-sm text-fg-subtle leading-relaxed">
        {analysis.coverage.articleText === 'full'
          ? `Read the full article (${analysis.coverage.articleChars.toLocaleString()} characters).`
          : 'Full article could not be read — this is based on the headline and feed summary.'}
        {analysis.coverage.unavailable.length > 0 && (
          <>
            {' '}
            {analysis.coverage.unavailable.length} feed(s) unavailable:{' '}
            {analysis.coverage.unavailable.join(', ')}.
          </>
        )}
      </div>
    </div>
  );
}
