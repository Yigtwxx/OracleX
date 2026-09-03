'use client';

import { AlertCircle, ExternalLink } from 'lucide-react';

import StageChecklist from '@/components/analysis/StageChecklist';
import { formatProbability } from '@/lib/polymarket-format';
import type {
  PolymarketAnalysis,
  PolymarketAnalysisJob,
  PolymarketClaim,
  PolymarketRefusal,
  PolymarketSourceRef,
  PolymarketVerdict,
} from '@/lib/api';

interface AnalysisPanelProps {
  verdict: PolymarketVerdict | null | undefined;
  job: PolymarketAnalysisJob | undefined;
  isStarting: boolean;
  onRun: () => void;
}

const LEANING_LABEL: Record<string, string> = {
  yes: 'Evidence favours Yes',
  no: 'Evidence favours No',
  unclear: 'Evidence does not settle it',
};

const LEANING_COLOR: Record<string, string> = {
  yes: 'var(--up)',
  no: 'var(--down)',
  unclear: 'var(--fg-muted)',
};

function sourceMap(sources: PolymarketSourceRef[]): Record<string, PolymarketSourceRef> {
  return Object.fromEntries(sources.map((s) => [s.id, s]));
}

function ClaimList({
  title,
  claims,
  sources,
}: {
  title: string;
  claims: PolymarketClaim[];
  sources: Record<string, PolymarketSourceRef>;
}) {
  if (claims.length === 0) return null;

  return (
    <div>
      <h4 className="text-xs font-semibold text-fg mb-1.5">{title}</h4>
      <ul className="space-y-2">
        {claims.map((claim) => (
          <li key={claim.text} className="text-xs text-fg-muted leading-relaxed">
            <span className="text-fg">{claim.text}</span>{' '}
            <span className="text-2xs text-fg-subtle">({claim.weight})</span>
            <span className="ml-1 inline-flex gap-1">
              {/* Every claim carries its sources as links. A claim whose ids did
                  not resolve was deleted server-side, so anything rendered here
                  is checkable — which is the only reason to show it. */}
              {claim.sources.map((id) => {
                const source = sources[id];
                if (!source) {
                  return (
                    <span key={id} className="text-2xs text-fg-subtle">
                      market
                    </span>
                  );
                }
                return (
                  <a
                    key={id}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={`${source.domain} — ${source.title}`}
                    className="text-2xs text-accent hover:underline"
                  >
                    {source.domain}
                  </a>
                );
              })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Refusal({ refusal }: { refusal: PolymarketRefusal }) {
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2">
        <AlertCircle className="w-4 h-4 text-warn shrink-0 mt-0.5" />
        <div>
          <h3 className="text-sm font-semibold text-fg">
            No sound analysis could be produced for this market
          </h3>
          <p className="text-xs text-fg-muted leading-relaxed mt-1">{refusal.explanation}</p>
        </div>
      </div>

      <p className="text-2xs text-fg-subtle">
        The odds, the movement and the holder concentration above are measured and unaffected — what
        is missing is a judgement, and there was not enough to base one on.
      </p>
    </div>
  );
}

function Verdict({ analysis }: { analysis: PolymarketAnalysis }) {
  const sources = sourceMap(analysis.sources);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <span className="text-sm font-semibold" style={{ color: LEANING_COLOR[analysis.leaning] }}>
          {LEANING_LABEL[analysis.leaning]}
        </span>
        <span className="text-2xs text-fg-subtle tabular-nums">
          Confidence in the evidence: {formatProbability(analysis.confidence)}
          {analysis.status === 'degraded' && ' · capped, thin evidence'}
        </span>
      </div>

      {analysis.bottom_line && (
        <p className="text-xs text-fg leading-relaxed">{analysis.bottom_line}</p>
      )}

      <ClaimList title="For" claims={analysis.claims_for} sources={sources} />
      <ClaimList title="Against" claims={analysis.claims_against} sources={sources} />

      {analysis.gaps.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-warn mb-1.5">What this rests on being thin</h4>
          <ul className="space-y-0.5">
            {analysis.gaps.map((gap) => (
              <li key={gap} className="text-2xs text-fg-subtle">
                {gap}
              </li>
            ))}
          </ul>
        </div>
      )}

      {analysis.sources.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-fg mb-1.5">Sources</h4>
          <ul className="space-y-0.5">
            {analysis.sources.map((source) => (
              <li key={source.id}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-2xs text-fg-muted hover:text-fg inline-flex items-center gap-1"
                >
                  <span className="font-mono text-fg-subtle">{source.id}</span>
                  {source.domain}
                  <ExternalLink className="w-2.5 h-2.5" />
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* The pruning is shown rather than hidden: a reader who can see that four
          claims were deleted for citing nothing knows what kind of answer this
          is. Silence about it would read as agreement. */}
      {analysis.attribution.claims_in > analysis.attribution.claims_kept && (
        <p className="text-2xs text-fg-subtle">
          {analysis.attribution.claims_in - analysis.attribution.claims_kept} of{' '}
          {analysis.attribution.claims_in} claims were dropped for citing sources we do not hold.
        </p>
      )}
    </div>
  );
}

/**
 * The bet analysis, on demand.
 *
 * Deliberately not started by opening the market. This pipeline runs several
 * searches, reads a handful of pages and makes two model calls, and it takes
 * minutes on the local chain — spending that on every card someone glances at
 * would be the wrong default. The reader asks for it.
 *
 * "Why this market exists" is no longer rendered here. It is a separate run with
 * its own panel above this one, because it is allowed to end in a labelled
 * hypothesis and this panel is not — mixing the two under one heading would put
 * a guess inside a verdict-shaped card.
 */
export default function AnalysisPanel({ verdict, job, isStarting, onRun }: AnalysisPanelProps) {
  const running = job?.status === 'queued' || job?.status === 'running';

  if (verdict) {
    return verdict.status === 'insufficient_evidence' ? (
      <Refusal refusal={verdict} />
    ) : (
      <Verdict analysis={verdict} />
    );
  }

  if (running || isStarting) {
    return (
      <StageChecklist
        stages={job?.stages ?? []}
        stageIndex={job?.stageIndex ?? 0}
        elapsedSeconds={job?.elapsedSeconds}
        dense
      />
    );
  }

  if (job?.status === 'error') {
    return (
      <p className="text-xs text-fg-muted">
        The analysis did not finish: {job.error ?? 'the run failed.'}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {/* No icon. `Sparkles` was the house sign for "a model did this" and
          oversold the button; a scale named the weighing but read as a verdict
          being passed. Nothing in the set says "goes and reads the news" without
          claiming something extra, and a label that says it plainly needs no
          help. The sentence underneath carries the rest. */}
      <button
        type="button"
        onClick={onRun}
        className="text-xs px-3 py-1.5 rounded border border-line text-fg hover:bg-surface-2 transition-colors"
      >
        Analyse this bet
      </button>
      <p className="text-2xs text-fg-subtle">
        Searches the news, reads what it finds and weighs both sides. Takes a couple of minutes, and
        will say so plainly if there is not enough to go on.
      </p>
    </div>
  );
}
