'use client';

import { Activity } from 'lucide-react';

import type { ChainAnomalyReport } from '@/lib/api';
import AiNote from '@/components/ui/AiNote';

interface AnomalyBannerProps {
  report: ChainAnomalyReport | undefined;
}

/**
 * Readings on the board that are not normal, and what they mean together.
 *
 * Renders nothing when nothing is unusual — the same discipline `DeviationBanner`
 * documents directly above it, and for the same reason: this is an element that
 * appears rather than updates, so its presence is itself the signal. A permanent
 * strip reporting that everything is fine is one more thing to scan past, and it
 * trains the reader to stop seeing the row entirely.
 *
 * Each sentence here is written on the server by the detector, so the board keeps
 * saying what is unusual whether or not a model is reachable; the note underneath
 * only adds why several readings might share a cause. `basis` rides on every line
 * because "fees are high" and "fees are high for this hour of day" are different
 * claims, and only the second one is supported.
 */
export default function AnomalyBanner({ report }: AnomalyBannerProps) {
  if (!report || report.anomalies.length === 0) return null;

  return (
    <div className="surface ai-surface px-4 py-2.5 flex items-start gap-2.5">
      <Activity className="w-3.5 h-3.5 text-warn shrink-0 mt-0.5" aria-hidden />

      <div className="min-w-0 flex flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          {report.anomalies.map((anomaly) => (
            <span
              key={`${anomaly.chain}:${anomaly.kind}`}
              className={`text-xs ${anomaly.severity === 'high' ? 'text-fg' : 'text-fg-muted'}`}
            >
              {anomaly.text}
            </span>
          ))}

          {report.suppressed > 0 && (
            <span className="text-2xs text-fg-subtle">
              {report.suppressed} further reading{report.suppressed === 1 ? '' : 's'} flagged
            </span>
          )}
        </div>

        <AiNote aiNote={report.note} />

        <p className="text-2xs text-fg-subtle">{report.coverage}</p>
      </div>
    </div>
  );
}
