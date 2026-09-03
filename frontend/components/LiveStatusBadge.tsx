'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useSystemHealth } from '@/hooks/useSystemHealth';
import { badgeAppearance, formatDetail, stateColor } from '@/lib/health-format';

/**
 * The header's live indicator, and the panel behind it.
 *
 * Replaces a static "Financial Intelligence Terminal" label. That text made a
 * claim the header could not back up; this one is answerable — every colour on
 * screen traces to a real upstream call the backend made.
 *
 * Opens on hover for a pointer and on click for everything else. Hover alone
 * would strand touch users, and click alone would make a glanceable indicator
 * cost a tap.
 */
export default function LiveStatusBadge() {
  const { snapshot, status, unreachable } = useSystemHealth();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const containerRef = useRef<HTMLDivElement>(null);

  const appearance = badgeAppearance(status);
  const categories = snapshot?.categories ?? [];

  // Close on Escape and on an outside click, so a panel opened by tap is not
  // stuck open on a device that never fires mouseleave.
  useEffect(() => {
    if (!open) return;

    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onPointerDown = (e: PointerEvent): void => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open]);

  return (
    <div
      ref={containerRef}
      className="relative ml-auto"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md border border-line hover:bg-surface transition-colors"
      >
        <span className="relative flex w-2 h-2">
          {appearance.pulse && (
            <span
              className="absolute inline-flex w-full h-full rounded-full opacity-60 animate-ping"
              style={{ backgroundColor: appearance.color }}
            />
          )}
          <span
            className="relative inline-flex w-2 h-2 rounded-full"
            style={{ backgroundColor: appearance.color }}
          />
        </span>
        {/* Polite rather than assertive: a provider recovering is worth
            announcing, but not worth interrupting whatever is being read. */}
        <span
          role="status"
          aria-live="polite"
          className="label tracking-wider"
          style={{ color: appearance.color }}
        >
          {appearance.label}
        </span>
      </button>

      {open && (
        <div
          id={panelId}
          className="absolute right-0 top-full mt-1 w-72 py-1.5 bg-surface border border-line rounded-lg shadow-lg z-50"
        >
          <div className="px-3 pb-1.5 text-[11px] text-fg-subtle border-b border-line">
            {unreachable ? 'API unreachable — last known state' : 'Data sources'}
          </div>

          {categories.length === 0 ? (
            <div className="px-3 py-2 text-[11px] text-fg-subtle">No data yet.</div>
          ) : (
            categories.map((category) => (
              <div
                key={category.key}
                className="flex items-center gap-2 px-3 py-1"
                title={category.providers.join(', ')}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ backgroundColor: stateColor(category.state) }}
                />
                <span className="text-[11px] text-fg truncate">{category.label}</span>
                <span className="ml-auto text-[11px] text-fg-subtle whitespace-nowrap">
                  {formatDetail(
                    category.state,
                    category.last_ok_at,
                    category.latency_ms,
                    category.detail
                  )}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
