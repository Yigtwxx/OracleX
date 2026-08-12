'use client';

import { Check, Loader2, Minus, SkipForward } from 'lucide-react';
import { useElapsed, formatElapsed } from '../analysis/StageChecklist';
import type { ChatStep, StepStatus } from '@/lib/chat-job';

interface StepTimelineProps {
  steps: ChatStep[];
  /** Tightens spacing so the list fits inside a chat bubble. */
  dense?: boolean;
}

/**
 * How each outcome reads at a glance.
 *
 * `empty` deliberately gets a check rather than a warning: the tool did its job
 * and there was nothing there, which is information, not a fault. Only `failed`
 * is red, because only `failed` means the answer is missing something it should
 * have had.
 */
const STATUS_STYLES: Record<StepStatus, { icon: JSX.Element; text: string }> = {
  pending: {
    icon: <span className="w-1.5 h-1.5 rounded-full bg-fg-subtle" />,
    text: 'text-fg-subtle',
  },
  running: {
    icon: <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />,
    text: 'text-fg',
  },
  done: { icon: <Check className="w-3.5 h-3.5 text-up" />, text: 'text-fg-muted' },
  empty: { icon: <Check className="w-3.5 h-3.5 text-fg-subtle" />, text: 'text-fg-subtle' },
  failed: { icon: <Minus className="w-3.5 h-3.5 text-down" />, text: 'text-fg-subtle' },
  skipped: {
    icon: <SkipForward className="w-3.5 h-3.5 text-fg-subtle" />,
    text: 'text-fg-subtle',
  },
};

/**
 * The live list of what the turn is doing.
 *
 * Rows arrive one at a time as the backend reports them, so each one animates in
 * — a list that grows without transition reads as a rendering glitch rather than
 * as progress. The running row carries a ticking counter for the same reason the
 * analysis stage list does: a long wait needs visible movement to be legible as
 * work rather than as a hang.
 */
export default function StepTimeline({ steps, dense = false }: StepTimelineProps) {
  if (steps.length === 0) return null;

  return (
    <ol className={`relative ${dense ? 'space-y-0.5' : 'space-y-1'}`}>
      {steps.map((step, index) => (
        <StepRow key={step.id} step={step} dense={dense} isLast={index === steps.length - 1} />
      ))}
    </ol>
  );
}

function StepRow({ step, dense, isLast }: { step: ChatStep; dense: boolean; isLast: boolean }) {
  const style = STATUS_STYLES[step.status];
  const running = step.status === 'running';

  return (
    <li className="step-in relative flex items-start gap-2.5">
      {/* The thread joining one step to the next. Stops at the last row so the
          line never dangles below the final item. */}
      {!isLast && (
        <span
          aria-hidden
          className="absolute left-2 top-5 bottom-0 w-px bg-line"
          style={{ transform: 'translateX(-0.5px)' }}
        />
      )}

      {/* No disc behind the icon: the thread stops above it, so the fill was
          never masking anything — on a transparent bubble it only reads as a
          chip drawn around each step. */}
      <span className="relative z-10 w-4 h-4 mt-1 shrink-0 flex items-center justify-center">
        {style.icon}
      </span>

      <span className={`flex-1 min-w-0 ${dense ? 'py-0.5' : 'py-1'}`}>
        <span className={`block ${dense ? 'text-sm' : 'text-base'} ${style.text}`}>
          {step.label}
        </span>
        {step.detail && (
          <span className="block text-xs text-fg-subtle truncate">{step.detail}</span>
        )}
      </span>

      <StepTiming step={step} running={running} />
    </li>
  );
}

function StepTiming({ step, running }: { step: ChatStep; running: boolean }) {
  // Hooks cannot be called conditionally, so the ticker always runs and only
  // its output is conditional.
  const elapsed = useElapsed(running ? 0 : undefined);

  if (running) {
    return (
      <span className="mt-1 text-xs text-fg-subtle tabnum font-mono">{formatElapsed(elapsed)}</span>
    );
  }
  if (step.durationSeconds === undefined) return null;
  return (
    <span className="mt-1 text-xs text-fg-subtle tabnum font-mono">
      {step.durationSeconds.toFixed(1)}s
    </span>
  );
}
