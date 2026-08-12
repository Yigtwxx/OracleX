'use client';

import { useEffect, useState } from 'react';
import { Check, Loader2 } from 'lucide-react';

export interface Stage {
  key: string;
  label: string;
}

interface StageChecklistProps {
  stages: Stage[];
  /** Index of the running stage; everything before it is done. */
  stageIndex: number;
  elapsedSeconds?: number;
  /**
   * Tightens spacing so the list fits a narrow column. The Oracle panel is 28%
   * of the viewport, which the report page's roomier layout does not have to
   * care about.
   */
  dense?: boolean;
}

/** Ticking elapsed counter — a long wait needs visible movement. */
export function useElapsed(startSeconds: number | undefined) {
  const [elapsed, setElapsed] = useState(startSeconds ?? 0);

  useEffect(() => {
    setElapsed(startSeconds ?? 0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [startSeconds]);

  return elapsed;
}

export function formatElapsed(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * The stage-by-stage progress list.
 *
 * Named stages rather than a spinner: a user who can see "Gathering evidence →
 * Judging price impact" knows the wait is work, not a hang.
 */
export default function StageChecklist({
  stages,
  stageIndex,
  elapsedSeconds,
  dense = false,
}: StageChecklistProps) {
  return (
    <ol className={dense ? 'space-y-0.5' : 'space-y-1'}>
      {stages.map((stage, index) => {
        const done = index < stageIndex;
        const active = index === stageIndex;

        return (
          <li
            key={stage.key}
            className={`flex items-center gap-2.5 rounded-md border transition-colors ${
              dense ? 'px-2 py-1.5' : 'px-3 py-2'
            } ${active ? 'border-line-strong bg-surface-2' : 'border-transparent'}`}
          >
            <span className="w-4 h-4 shrink-0 flex items-center justify-center">
              {done ? (
                <Check className="w-3.5 h-3.5 text-up" />
              ) : active ? (
                <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />
              ) : (
                <span className="w-1.5 h-1.5 rounded-full bg-fg-subtle" />
              )}
            </span>
            <span
              className={`${dense ? 'text-sm' : 'text-base'} ${
                active ? 'text-fg' : done ? 'text-fg-muted' : 'text-fg-subtle'
              }`}
            >
              {stage.label}
            </span>
            {active && elapsedSeconds !== undefined && (
              <span className="ml-auto text-sm text-fg-subtle tabnum font-mono">
                {formatElapsed(elapsedSeconds)}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
