'use client';

import { AlertTriangle, ArrowLeft, Calendar, Loader2, RotateCw } from 'lucide-react';
import type { AnalysisJob, AnalysisReport, TimeFrame } from '@/lib/api';
import ReportMarkdown from './ReportMarkdown';

interface ReportViewProps {
  timeframe: TimeFrame;
  report: AnalysisReport | undefined;
  isLoading: boolean;
  /** Set while a fresh run for this horizon is in flight, started anywhere. */
  runningJob?: AnalysisJob;
  onBack: () => void;
  onRerun: () => void;
}

export default function ReportView({
  timeframe,
  report,
  isLoading,
  runningJob,
  onBack,
  onRerun,
}: ReportViewProps) {
  const unavailable = report?.unavailable ?? [];
  const runningStage = runningJob?.stages[runningJob.stageIndex]?.label;

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 mb-4">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg transition-colors shrink-0"
          >
            <ArrowLeft className="w-3 h-3" />
            Timeframes
          </button>
          <span className="text-fg-subtle">/</span>
          <span className="text-md font-semibold text-fg capitalize">{timeframe}</span>
          {report?.stale && (
            <span className="text-2xs px-1.5 py-0.5 rounded bg-warn-bg text-warn border border-warn shrink-0">
              Stale
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs text-fg-subtle tabnum">
            <Calendar className="w-3 h-3" />
            {report?.timestamp ? new Date(report.timestamp).toLocaleString('en-GB') : '—'}
          </span>
          <button
            onClick={onRerun}
            className={`flex items-center gap-1.5 px-2.5 py-1 border rounded-md text-sm transition-colors ${
              runningJob
                ? 'bg-surface-2 border-accent text-accent'
                : 'bg-surface-2 border-line text-fg-muted hover:text-fg hover:border-line-strong'
            }`}
          >
            {runningJob ? (
              <>
                <Loader2 className="w-3 h-3 animate-spin" />
                {runningStage ? `Running · ${runningStage}` : 'Queued…'}
              </>
            ) : (
              <>
                <RotateCw className="w-3 h-3" />
                Re-run
              </>
            )}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden custom-scrollbar">
        {isLoading ? (
          <p className="text-base text-fg-subtle">Loading report…</p>
        ) : report?.content ? (
          <>
            {unavailable.length > 0 && (
              <div className="flex items-start gap-2 mb-4 px-3 py-2 rounded-md bg-warn-bg border border-warn">
                <AlertTriangle className="w-3.5 h-3.5 text-warn shrink-0 mt-0.5" />
                <p className="text-sm text-fg-muted">
                  Built on partial data — {unavailable.join(', ')}{' '}
                  {unavailable.length > 1 ? 'were' : 'was'} unavailable. The report flags what could
                  not be assessed.
                </p>
              </div>
            )}
            <ReportMarkdown content={report.content} />
          </>
        ) : (
          <p className="text-base text-fg-subtle">
            No report stored for this timeframe yet. Use Re-run to generate one.
          </p>
        )}
      </div>
    </div>
  );
}
