'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Bell } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { describeAlarmShort } from '@/lib/alarms/describe';
import { getAlarmSource } from '@/lib/alarms/registry';
import { ALARM_ICONS } from './icons';

/** Rows before the panel stops listing and starts counting. */
const LISTED = 6;

/**
 * The alarm entry point, in the header chrome beside the Pizza Index.
 *
 * It used to live in the Chart panel's header, which was right when the only
 * alarm was a price alarm. It is app-wide now, so it sits with the other
 * app-wide readings rather than inside one panel.
 *
 * Shaped like PizzaIndexBadge and LiveStatusBadge on purpose — same border,
 * same hover, same 3.5 icon — and like them it opens a panel on hover. The
 * difference is what the click does: those two toggle their panel, this one
 * opens the Alarm Center, because the badge is a way in rather than a reading.
 *
 * That split is also why the panel is hover-and-focus only, with no tap to open
 * it. A touch device has no hover, and there is nothing to strand: the tap that
 * would have opened this panel opens the Alarm Center, which shows the same
 * alarms with room to edit them.
 */
export default function AlarmBell() {
  const openAlarmModal = useStore((state) => state.openAlarmModal);
  const alarms = useStore((state) => state.alarms);

  const [open, setOpen] = useState(false);
  const panelId = useId();
  const containerRef = useRef<HTMLDivElement>(null);

  const active = alarms.filter((alarm) => alarm.enabled);
  const pausedCount = alarms.length - active.length;

  // Escape closes a panel opened by keyboard focus, which otherwise stays up
  // until focus moves — the same reason the other two badges do this.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open]);

  const summary =
    active.length === 0
      ? 'No active alarms'
      : `${active.length} active alarm${active.length === 1 ? '' : 's'}`;

  return (
    <div
      ref={containerRef}
      className="relative shrink-0"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => {
          setOpen(false);
          openAlarmModal();
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Alarm Center — ${summary}`}
        className="relative flex shrink-0 items-center gap-1.5 rounded-md border border-line px-2 py-1 transition-colors hover:bg-surface-2"
      >
        <Bell className="h-3.5 w-3.5 shrink-0 text-fg-muted" />
        {active.length > 0 && (
          <span className="text-xs font-mono tabnum text-fg">{active.length}</span>
        )}
      </button>

      {open && (
        <div
          id={panelId}
          role="tooltip"
          className="absolute right-0 top-full z-50 mt-1 w-72 rounded-lg border border-line bg-surface py-1.5 shadow-lg"
        >
          <div className="flex items-baseline gap-2 border-b border-line px-3 pb-1.5">
            <span className="text-[11px] text-fg">{summary}</span>
            {pausedCount > 0 && (
              <span className="ml-auto text-[11px] text-fg-subtle">{pausedCount} paused</span>
            )}
          </div>

          {active.length === 0 ? (
            <div className="px-3 py-2 text-[11px] text-fg-subtle">
              {alarms.length === 0
                ? 'Nothing is being watched. Click to set one up.'
                : 'Every alarm is paused. Click to resume one.'}
            </div>
          ) : (
            <>
              {active.slice(0, LISTED).map((alarm) => {
                const Icon = ALARM_ICONS[getAlarmSource(alarm.sourceId).icon];
                return (
                  <div key={alarm.id} className="flex items-center gap-2 px-3 py-1">
                    <Icon className="h-3 w-3 shrink-0 text-fg-subtle" />
                    {/* `title` carries the full sentence, since the row is
                        narrow enough that a long rule is always truncated. */}
                    <span
                      className="truncate text-[11px] text-fg"
                      title={describeAlarmShort(alarm)}
                    >
                      {describeAlarmShort(alarm)}
                    </span>
                  </div>
                );
              })}
              {active.length > LISTED && (
                <div className="px-3 pt-1 text-[11px] text-fg-subtle">
                  +{active.length - LISTED} more
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
