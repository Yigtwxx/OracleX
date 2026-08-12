'use client';

import { AlertCircle, ArrowLeft, RotateCw, Square } from 'lucide-react';
import StageChecklist, { formatElapsed, useElapsed } from './StageChecklist';
import type { AnalysisJob, TimeFrame } from '@/lib/api';

interface AnalysisProgressProps {
  timeframe: TimeFrame;
  job: AnalysisJob | undefined;
  /** Set when the job could not be started or polled at all. */
  error?: string;
  onBack: () => void;
  onRetry: () => void;
  /** Undefined until there is a job id to stop — the first moments of a start. */
  onStop?: () => void;
  isStopping: boolean;
}

export default function AnalysisProgress({
  timeframe,
  job,
  error,
  onBack,
  onRetry,
  onStop,
  isStopping,
}: AnalysisProgressProps) {
  const elapsed = useElapsed(job?.elapsedSeconds);
  const failure = error ?? job?.error;

  if (failure) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="surface p-5 max-w-md w-full border-down">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="w-4 h-4 text-down" />
            <h3 className="text-md font-semibold text-fg">Analysis failed</h3>
          </div>
          <p className="text-base text-fg-muted mb-1">
            The {timeframe} report could not be generated.
          </p>
          <p className="text-sm text-fg-subtle font-mono break-words mb-4">{failure}</p>
          <div className="flex gap-2">
            <button
              onClick={onRetry}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-accent text-white text-sm rounded-md hover:opacity-90 transition-opacity"
            >
              <RotateCw className="w-3 h-3" />
              Retry
            </button>
            <button
              onClick={onBack}
              className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-2 border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              <ArrowLeft className="w-3 h-3" />
              Back
            </button>
          </div>
        </div>
      </div>
    );
  }

  const stages = job?.stages ?? [];
  const currentIndex = job?.stageIndex ?? -1;

  return (
    <div className="h-full flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="flex items-baseline justify-between mb-4">
          <h3 className="text-md font-semibold text-fg capitalize">
            Generating {timeframe} report
          </h3>
          <span className="text-sm text-fg-subtle tabnum font-mono">{formatElapsed(elapsed)}</span>
        </div>

        <StageChecklist stages={stages} stageIndex={currentIndex} />

        <p className="text-sm text-fg-subtle mt-4">
          This usually takes a few minutes. You can leave this page — the run continues and the
          report will be waiting.
        </p>

        <div className="flex items-center gap-4 mt-4">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg transition-colors"
          >
            <ArrowLeft className="w-3 h-3" />
            Back to timeframes
          </button>
          {onStop && (
            <button
              onClick={onStop}
              disabled={isStopping}
              className="flex items-center gap-1.5 text-sm text-fg-muted hover:text-down transition-colors disabled:opacity-50"
            >
              <Square className="w-3 h-3" />
              {isStopping ? 'Stopping…' : 'Stop analysis'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
