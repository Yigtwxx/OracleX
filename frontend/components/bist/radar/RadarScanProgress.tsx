'use client';

import StageChecklist, { formatElapsed, useElapsed } from '@/components/analysis/StageChecklist';
import type { RadarJob } from '@/lib/bist-api';

/**
 * The running scan: its five stages, the ticker count inside the long ones, and
 * the clock.
 *
 * Named stages rather than a spinner, for the same reason the report page has
 * them: a reader who can see "Mali tablolar 61/100" knows the minute is work
 * and not a hang, and knows roughly how much of it is left.
 */
export default function RadarScanProgress({ job }: { job: RadarJob }) {
  const elapsed = useElapsed(job.elapsedSeconds);
  const progress = job.progress;

  return (
    <div className="surface surface-flat space-y-3 p-3">
      <div className="flex items-center justify-between">
        <span className="label">Tarama sürüyor</span>
        <span className="tabnum text-xs text-fg-subtle">{formatElapsed(elapsed)}</span>
      </div>
      <StageChecklist stages={job.stages} stageIndex={job.stageIndex} dense />
      {progress && progress.stage === job.stage && (
        <p className="tabnum text-xs text-fg-muted">
          {progress.done} / {progress.total} hisse
        </p>
      )}
    </div>
  );
}
