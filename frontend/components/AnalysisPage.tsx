'use client';

import { useEffect, useState } from 'react';
import { BrainCircuit } from 'lucide-react';
import {
  useActiveAnalysisJobs,
  useAnalysisJob,
  useAnalysisReport,
  useCancelAnalysis,
  useReportSummaries,
  useStartAnalysis,
} from '@/hooks/queries';
import type { TimeFrame } from '@/lib/api';
import AnalysisProgress from '@/components/analysis/AnalysisProgress';
import NotesPanel from '@/components/analysis/NotesPanel';
import ReportView from '@/components/analysis/ReportView';
import TimeframeSelector from '@/components/analysis/TimeframeSelector';

/**
 * Analysis page.
 *
 * The left pane is a three-state view: pick a horizon, watch a run, read the
 * report. Opening the page only reads report freshness — generation is always
 * an explicit action, because it costs minutes of LLM time and used to fail
 * silently behind a placeholder report when triggered on mount.
 *
 * Which horizon is running is *not* held here. Leaving the tab unmounts this
 * component and would drop that state while the run continued server-side, so
 * the page came back looking as if nothing had ever been started; it is read
 * from the server instead and survives navigation and reloads alike.
 */
export default function AnalysisPage() {
  const [timeframe, setTimeframe] = useState<TimeFrame | undefined>(undefined);
  const [jobId, setJobId] = useState<string | undefined>(undefined);

  const summariesQuery = useReportSummaries();
  const reportQuery = useAnalysisReport(timeframe);
  const startAnalysis = useStartAnalysis();
  const cancelAnalysis = useCancelAnalysis();
  const jobQuery = useAnalysisJob(jobId);
  const activeJobsQuery = useActiveAnalysisJobs();

  const job = jobQuery.data;
  const runningJobs = new Map(
    (activeJobsQuery.data ?? []).map((active) => [active.timeframe, active])
  );

  // A finished run leaves the progress view for the report it just produced.
  useEffect(() => {
    if (job?.status === 'done') {
      setTimeframe(job.timeframe);
      setJobId(undefined);
    }
  }, [job?.status, job?.timeframe]);

  /** Re-attach to the run for a horizon instead of starting a second one. */
  const handleWatch = (target: TimeFrame) => {
    const inFlight = runningJobs.get(target);
    if (!inFlight) return;
    setTimeframe(target);
    setJobId(inFlight.jobId);
  };

  const handleRun = (target: TimeFrame) => {
    // The backend already single-flights per horizon, but attaching locally
    // makes the click land on the progress view without a round trip.
    if (runningJobs.has(target)) {
      handleWatch(target);
      return;
    }
    setTimeframe(target);
    startAnalysis.mutate(target, {
      onSuccess: (started) => {
        // A job that already finished within its retention window has
        // its report cached; there is nothing to watch.
        if (started.status === 'done') return;
        setJobId(started.jobId);
      },
    });
  };

  /**
   * Stop a run. Takes the job id rather than the horizon so the button in the
   * progress view works on the very first tick, before the active-jobs poll has
   * caught up with the run it is already watching.
   */
  const handleStop = (target: string | undefined) => {
    if (!target) return;
    cancelAnalysis.mutate(target, {
      onSuccess: () => {
        setJobId(undefined);
        startAnalysis.reset();
      },
    });
  };

  const handleBackToTimeframes = () => {
    setTimeframe(undefined);
    setJobId(undefined);
    startAnalysis.reset();
  };

  const isStarting = startAnalysis.isPending;
  const showProgress = isStarting || !!jobId || startAnalysis.isError;

  return (
    <div className="h-full grid grid-cols-1 lg:grid-cols-[65%_35%] overflow-hidden">
      {/* LEFT PANE: ANALYSIS REPORT */}
      <div className="flex flex-col min-h-0 border-r border-line overflow-hidden p-4">
        <div className="flex items-center gap-2 mb-3">
          <BrainCircuit className="w-3.5 h-3.5 text-fg-muted" />
          <div>
            <h2 className="text-md font-semibold text-fg">Market Intelligence</h2>
            <p className="text-xs text-fg-subtle">
              Institutional-grade reports built from a live market snapshot
            </p>
          </div>
        </div>

        <div className="flex-1 min-h-0 surface p-5 overflow-hidden">
          {showProgress && timeframe ? (
            <AnalysisProgress
              timeframe={timeframe}
              job={job}
              error={
                startAnalysis.error?.message ??
                (jobQuery.isError ? 'The report job is no longer available.' : undefined)
              }
              onBack={handleBackToTimeframes}
              onRetry={() => handleRun(timeframe)}
              onStop={jobId ? () => handleStop(jobId) : undefined}
              isStopping={cancelAnalysis.isPending}
            />
          ) : timeframe ? (
            <ReportView
              timeframe={timeframe}
              report={reportQuery.data}
              isLoading={reportQuery.isLoading}
              runningJob={runningJobs.get(timeframe)}
              onBack={handleBackToTimeframes}
              onRerun={() => handleRun(timeframe)}
            />
          ) : (
            <TimeframeSelector
              summaries={summariesQuery.data}
              isLoading={summariesQuery.isLoading}
              runningJobs={runningJobs}
              onOpen={setTimeframe}
              onRun={handleRun}
              onWatch={handleWatch}
              onStop={(target) => handleStop(runningJobs.get(target)?.jobId)}
              isStopping={cancelAnalysis.isPending}
            />
          )}
        </div>
      </div>

      {/* RIGHT PANE: USER NOTES */}
      <div className="flex flex-col min-h-0 overflow-hidden p-4">
        <NotesPanel />
      </div>
    </div>
  );
}
