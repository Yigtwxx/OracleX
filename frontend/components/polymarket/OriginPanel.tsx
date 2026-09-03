'use client';

import { ExternalLink } from 'lucide-react';

import StageChecklist from '@/components/analysis/StageChecklist';
import type { PolymarketOriginJob, PolymarketOriginReport, PolymarketSourceRef } from '@/lib/api';

interface OriginPanelProps {
  report: PolymarketOriginReport | null | undefined;
  job: PolymarketOriginJob | undefined;
  isStarting: boolean;
}

function sourceMap(sources: PolymarketSourceRef[]): Record<string, PolymarketSourceRef> {
  return Object.fromEntries(sources.map((s) => [s.id, s]));
}

/**
 * The traced answer: a rationale and the dated stories that sit inside the
 * windows where the price actually moved.
 */
function Traced({ report }: { report: PolymarketOriginReport }) {
  const sources = sourceMap(report.sources);

  return (
    <div className="space-y-2">
      {report.opening_rationale && (
        <p className="text-xs text-fg leading-relaxed">{report.opening_rationale}</p>
      )}
      {report.triggers.length > 0 && (
        <ul className="space-y-1">
          {report.triggers.map((trigger) => {
            const source = sources[trigger.source_id];
            return (
              <li key={trigger.source_id} className="text-xs text-fg-muted leading-relaxed">
                <span className="font-mono text-2xs text-fg-subtle tabular-nums mr-1.5">
                  {trigger.occurred_at ? trigger.occurred_at.slice(0, 10) : '—'}
                </span>
                {trigger.summary}
                {source && (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={`${source.domain} — ${source.title}`}
                    className="ml-1.5 text-2xs text-accent hover:underline inline-flex items-center gap-0.5"
                  >
                    {source.domain}
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * The hypothesis, and it has to keep looking like one.
 *
 * The badge, the muted body and the visible working are the whole reason this
 * branch is allowed to exist. Styled like the traced answer it would read as a
 * finding, and a reader who cannot tell "we found the story" from "this is the
 * kind of thing that opens a market like this" is worse off than one who was
 * shown nothing.
 */
function Conjectured({ report }: { report: PolymarketOriginReport }) {
  return (
    <div className="space-y-2">
      <span className="inline-flex items-center gap-1.5 text-2xs text-warn border border-warn/40 rounded-full px-2 py-0.5">
        <span className="w-1 h-1 rounded-full bg-warn" aria-hidden />
        Unverified — a possible reason
      </span>
      <p className="text-xs text-fg-muted leading-relaxed italic">{report.conjecture}</p>
      {report.conjecture_basis.length > 0 && (
        <ul className="space-y-0.5">
          {report.conjecture_basis.map((line) => (
            <li key={line} className="text-2xs text-fg-subtle">
              {line}
            </li>
          ))}
        </ul>
      )}
      <p className="text-2xs text-fg-subtle">
        No reporting was found inside the windows where this market&apos;s price moved, so nothing
        above is sourced. It is not used anywhere in the analysis.
      </p>
    </div>
  );
}

/** Nothing found and nothing worth guessing — say what was tried. */
function Undetermined({ report }: { report: PolymarketOriginReport }) {
  const searched = report.attempted.length;
  const empty = report.attempted.filter((a) => a.outcome === 'empty').length;

  return (
    <p className="text-xs text-fg-muted leading-relaxed">
      {searched > 0
        ? `${searched} searches were run against the days this market moved and ${empty} came back empty. Nothing explains why it was opened, and there was not enough to suggest what might have.`
        : 'The days this market moved could not be searched, so nothing can be said about why it was opened.'}
    </p>
  );
}

/**
 * Why this bet was opened, as its own answer.
 *
 * A separate job from the verdict, started by the same click and rendered as
 * soon as it lands — which is usually well before the analysis, and sometimes
 * after it. Neither panel waits for the other.
 */
export default function OriginPanel({ report, job, isStarting }: OriginPanelProps) {
  const running = job?.status === 'queued' || job?.status === 'running';

  if (!report && !running && !isStarting && job?.status !== 'error') return null;

  return (
    <div className="space-y-2 mb-4">
      <h4 className="text-xs font-semibold text-fg">Why this market exists</h4>

      {report ? (
        report.status === 'traced' ? (
          <Traced report={report} />
        ) : report.status === 'conjectured' ? (
          <Conjectured report={report} />
        ) : (
          <Undetermined report={report} />
        )
      ) : job?.status === 'error' ? (
        <p className="text-xs text-fg-muted">
          The trace did not finish: {job.error ?? 'the run failed.'}
        </p>
      ) : (
        <StageChecklist
          stages={job?.stages ?? []}
          stageIndex={job?.stageIndex ?? 0}
          elapsedSeconds={job?.elapsedSeconds}
          dense
        />
      )}
    </div>
  );
}
