'use client';

import { AlertTriangle, ArrowRight, Clock, Loader2, Play, Square } from 'lucide-react';
import { TIME_FRAMES, type AnalysisJob, type ReportSummary, type TimeFrame } from '@/lib/api';
import { formatElapsed, useElapsed } from './StageChecklist';

/** What each horizon actually covers, so the choice is informed. */
const TIMEFRAME_SCOPE: Record<TimeFrame, { title: string; scope: string; sources: string }> = {
  daily: {
    title: 'Daily',
    scope: 'Intraday positioning and the last 24 hours of flow.',
    sources: '30 headlines · 24h liquidations · 4h technicals',
  },
  weekly: {
    title: 'Weekly',
    scope: 'The week’s regime shift, rotation and cross-asset read.',
    sources: '60 headlines · 7d liquidations · 4h technicals',
  },
  monthly: {
    title: 'Monthly',
    scope: 'Structural trend, sector leadership and macro backdrop.',
    sources: '100 headlines · 30d liquidations · 4h technicals',
  },
};

function formatAge(seconds: number | undefined): string {
  if (seconds === undefined) return 'Never generated';
  if (seconds < 60) return 'Generated just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `Generated ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Generated ${hours}h ago`;
  return `Generated ${Math.floor(hours / 24)}d ago`;
}

/**
 * Live line for a horizon that is generating right now.
 *
 * Its own component only so the ticking counter can be a hook — the card list
 * is a map, and the stage name plus a moving clock is what tells the user the
 * run they started is still going rather than lost.
 */
function RunningStatus({ job }: { job: AnalysisJob }) {
  const elapsed = useElapsed(job.elapsedSeconds);
  const stage = job.stages[job.stageIndex]?.label;

  return (
    <span className="flex items-center gap-1.5 text-accent">
      <Loader2 className="w-3 h-3 animate-spin" />
      {stage ? `Running · ${stage}` : 'Queued…'}
      <span className="tabnum font-mono">{formatElapsed(elapsed)}</span>
    </span>
  );
}

interface TimeframeSelectorProps {
  summaries: Record<TimeFrame, ReportSummary> | undefined;
  isLoading: boolean;
  /** Horizons generating right now, whoever started the run. */
  runningJobs: Map<TimeFrame, AnalysisJob>;
  onOpen: (timeframe: TimeFrame) => void;
  onRun: (timeframe: TimeFrame) => void;
  /** Re-attach to a run already in flight rather than starting another. */
  onWatch: (timeframe: TimeFrame) => void;
  onStop: (timeframe: TimeFrame) => void;
  isStopping: boolean;
}

export default function TimeframeSelector({
  summaries,
  isLoading,
  runningJobs,
  onOpen,
  onRun,
  onWatch,
  onStop,
  isStopping,
}: TimeframeSelectorProps) {
  return (
    <div className="h-full overflow-y-auto overflow-x-hidden custom-scrollbar p-1">
      <div className="mb-5">
        <h3 className="text-lg font-semibold text-fg mb-1">Choose a reporting horizon</h3>
        <p className="text-base text-fg-muted max-w-xl">
          Each report is built from a live market snapshot — prices, breadth, technical levels,
          liquidations and headlines — then drafted and fact-checked against that snapshot.
          Generation takes a few minutes and only runs when you ask for it.
        </p>
      </div>

      <div className="space-y-2.5">
        {TIME_FRAMES.map((timeframe) => {
          const scope = TIMEFRAME_SCOPE[timeframe];
          const summary = summaries?.[timeframe];
          const hasReport = !!summary?.generatedAt;
          const runningJob = runningJobs.get(timeframe);

          return (
            <div
              key={timeframe}
              className={`surface p-4 flex flex-col sm:flex-row sm:items-center gap-4 transition-colors ${
                runningJob ? 'border-accent' : 'hover:border-line-strong'
              }`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h4 className="text-md font-semibold text-fg">{scope.title}</h4>
                  {runningJob && (
                    <span className="text-2xs px-1.5 py-0.5 rounded bg-surface-2 text-accent border border-accent">
                      Generating
                    </span>
                  )}
                  {hasReport && summary?.stale && (
                    <span className="text-2xs px-1.5 py-0.5 rounded bg-warn-bg text-warn border border-warn">
                      Stale
                    </span>
                  )}
                </div>
                <p className="text-base text-fg-muted mb-2">{scope.scope}</p>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-subtle">
                  <span className="font-mono">{scope.sources}</span>
                  {runningJob ? (
                    <RunningStatus job={runningJob} />
                  ) : (
                    <span className="flex items-center gap-1 tabnum">
                      <Clock className="w-3 h-3" />
                      {isLoading ? 'Checking…' : formatAge(summary?.ageSeconds)}
                    </span>
                  )}
                  {!!summary?.unavailable.length && (
                    <span className="flex items-center gap-1 text-warn">
                      <AlertTriangle className="w-3 h-3" />
                      {summary.unavailable.length} feed
                      {summary.unavailable.length > 1 ? 's' : ''} missing
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {hasReport && (
                  <button
                    onClick={() => onOpen(timeframe)}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-2 border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
                  >
                    Open
                    <ArrowRight className="w-3 h-3" />
                  </button>
                )}
                {runningJob ? (
                  <>
                    <button
                      onClick={() => onStop(timeframe)}
                      disabled={isStopping}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-2 border border-line rounded-md text-sm text-fg-muted hover:text-down hover:border-down transition-colors disabled:opacity-50"
                    >
                      <Square className="w-3 h-3" />
                      {isStopping ? 'Stopping…' : 'Stop'}
                    </button>
                    <button
                      onClick={() => onWatch(timeframe)}
                      className="flex items-center gap-1.5 px-2.5 py-1.5 bg-accent text-white text-sm rounded-md hover:opacity-90 transition-opacity"
                    >
                      <Loader2 className="w-3 h-3 animate-spin" />
                      View progress
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => onRun(timeframe)}
                    className="flex items-center gap-1.5 px-2.5 py-1.5 bg-accent text-white text-sm rounded-md hover:opacity-90 transition-opacity"
                  >
                    <Play className="w-3 h-3" />
                    {hasReport ? 'Re-run' : 'Run analysis'}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
