'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, Check, RotateCw } from 'lucide-react';
import Logo from '@/components/ui/Logo';
import type { ReadinessSnapshot, ReadinessStep } from '@/hooks/useReadiness';

interface BootSplashProps {
  snapshot: ReadinessSnapshot | undefined;
  /** Show the failure state: backend unreachable, or a required step down. */
  failed: boolean;
  onRetry: () => void;
}

/** How long to wait before explaining the wait rather than just showing it. */
const HINT_AFTER_MS = 6000;

function formatDuration(ms: number | null): string {
  if (ms === null) return '';
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/**
 * The running clock under the bar.
 *
 * Always seconds to one decimal, never the `formatDuration` millisecond form:
 * a readout that spends its first second showing "0ms" reads as a stuck zero
 * rather than as a timer, which is the opposite of what it is there to say.
 */
function formatElapsed(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Time spent on this splash, or `null` while the clock has never ticked.
 *
 * Before the backend answers once there are no steps to render, so this counter
 * is the only evidence the screen is still working rather than stuck. That makes
 * a *frozen* counter actively misleading, and it is a real failure mode: when a
 * chunk fails to load the client never hydrates, so this effect never runs and
 * the CSS-only progress bar keeps animating over a dead page. Starting at `null`
 * rather than `0` means the number is server-rendered nowhere — its presence is
 * itself proof that client JS is alive, and its absence says the opposite
 * instead of lying with a stuck "0.0s".
 */
function useWaitedMs(active: boolean): number | null {
  const [waited, setWaited] = useState<number | null>(null);

  useEffect(() => {
    if (!active) return;
    const startedAt = Date.now();
    // Show the clock immediately rather than after the first interval, now that
    // reaching this line is the signal being reported.
    setWaited(0);
    // Fast enough that the tenths place actually counts rather than skipping.
    const id = setInterval(() => setWaited(Date.now() - startedAt), 100);
    return () => clearInterval(id);
  }, [active]);

  return waited;
}

/**
 * The status marker for one step.
 *
 * Only a failure is coloured — the design system reserves colour for meaning,
 * so a list of successful steps stays neutral and the one problem stands out.
 */
function StepMarker({ state }: { state: ReadinessStep['state'] }) {
  if (state === 'ok') {
    return <Check className="w-3.5 h-3.5 text-fg-muted" aria-hidden />;
  }
  if (state === 'failed') {
    return <AlertTriangle className="w-3.5 h-3.5 text-warn" aria-hidden />;
  }
  if (state === 'running') {
    return <span className="w-1.5 h-1.5 rounded-full bg-fg animate-pulse mx-1" aria-hidden />;
  }
  return <span className="w-1.5 h-1.5 rounded-full bg-fg-subtle mx-1" aria-hidden />;
}

function StepRow({ step }: { step: ReadinessStep }) {
  const done = step.state === 'ok';
  const failed = step.state === 'failed';

  return (
    <li className="flex items-baseline gap-3 py-1">
      <span className="w-5 flex justify-center self-center shrink-0">
        <StepMarker state={step.state} />
      </span>
      <span
        className={`flex-1 text-base ${done ? 'text-fg-muted' : failed ? 'text-fg' : 'text-fg'}`}
      >
        {step.label}
        {failed && step.error && (
          <span className="block text-xs text-fg-subtle mt-0.5">{step.error}</span>
        )}
      </span>
      <span className="text-xs font-mono tabnum text-fg-subtle shrink-0">
        {step.state === 'running' ? '…' : formatDuration(step.duration_ms)}
      </span>
    </li>
  );
}

/**
 * Full-screen startup gate.
 *
 * Shown while the backend warms up, which takes tens of seconds from cold. The
 * per-step list exists because of that wait: it is the difference between a
 * screen that looks hung and one that is visibly working.
 */
export default function BootSplash({ snapshot, failed, onRetry }: BootSplashProps) {
  const steps = snapshot?.steps ?? [];
  const settled = steps.filter((s) => s.state === 'ok' || s.state === 'failed').length;
  const progress = steps.length > 0 ? (settled / steps.length) * 100 : 0;
  const waitedMs = useWaitedMs(!failed);
  const readout = [
    steps.length > 0 ? `${settled}/${steps.length}` : null,
    waitedMs !== null ? formatElapsed(waitedMs) : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div
      className="h-screen w-screen flex items-center justify-center bg-bg px-6"
      role="status"
      aria-live="polite"
      aria-busy={!failed}
    >
      <div className="w-full max-w-sm">
        <Logo size={28} className="text-fg mx-auto mb-4" />
        <h1 className="text-sm font-semibold tracking-[0.2em] text-fg text-center mb-8">
          ORACLE-X
        </h1>

        {failed ? (
          <div className="text-center">
            <AlertTriangle className="w-5 h-5 text-warn mx-auto mb-3" aria-hidden />
            <p className="text-base text-fg mb-1">Sunucuya bağlanılamıyor</p>
            <p className="text-xs text-fg-subtle mb-5">
              Backend çalışıyor mu? Konsolda hata var mı kontrol edin.
            </p>
            {steps.some((s) => s.state === 'failed') && (
              <ul className="text-left mb-5 border-t border-line pt-2">
                {steps
                  .filter((s) => s.state === 'failed')
                  .map((step) => (
                    <StepRow key={step.key} step={step} />
                  ))}
              </ul>
            )}
            <button
              onClick={onRetry}
              className="inline-flex items-center gap-2 px-3 py-1.5 text-base bg-surface border border-line rounded-md text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
            >
              <RotateCw className="w-3.5 h-3.5" aria-hidden />
              Tekrar dene
            </button>
          </div>
        ) : (
          <>
            <ul className="mb-5">
              {steps.length > 0 ? (
                steps.map((step) => <StepRow key={step.key} step={step} />)
              ) : (
                <li className="text-base text-fg-muted text-center py-1">Sunucuya bağlanılıyor…</li>
              )}
            </ul>

            <div className="border-t border-line pt-3">
              <div className="h-0.5 w-full bg-surface-2 rounded-full overflow-hidden">
                {/* The step list is reported by the backend, so before the first
                    answer there is no progress to show. An indeterminate bar
                    says "still trying" where a bar stuck at 0% says "hung". */}
                {steps.length > 0 ? (
                  <div
                    className="h-full bg-fg-muted transition-[width] duration-500 ease-out"
                    style={{ width: `${progress}%` }}
                  />
                ) : (
                  <div className="h-full w-1/3 bg-fg-muted animate-boot-scan" />
                )}
              </div>
              {/* The step count is the real progress, but it legitimately sits
                  at 0 while the first step runs — so the clock rides alongside
                  it and keeps something visibly moving the whole time. Built by
                  joining the parts that exist: the clock is absent until it
                  ticks, and a hardcoded separator would leave "2/5 · " dangling
                  behind nothing. */}
              {readout && (
                <p className="mt-2 text-xs font-mono tabnum text-fg-subtle text-right">{readout}</p>
              )}
            </div>

            {steps.length === 0 && waitedMs !== null && waitedMs >= HINT_AFTER_MS && (
              <p className="mt-3 text-xs text-fg-subtle text-center">
                Backend hâlâ açılıyor olabilir. İlk açılış birkaç saniye sürer.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
