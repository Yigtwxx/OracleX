'use client';

import { useStore } from '@/store/useStore';
import { getAlarmSource } from '@/lib/alarms/registry';
import { ALARM_ICONS } from './icons';
import { EmptyState } from './AlarmList';

const TIME_FORMAT = new Intl.DateTimeFormat('en-US', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

export default function AlarmHistory() {
  const history = useStore((state) => state.alarmHistory);
  const clearAlarmHistory = useStore((state) => state.clearAlarmHistory);

  if (history.length === 0) {
    return (
      <EmptyState
        title="History is empty"
        body="When an alarm fires, the reading and the time it fired stay here."
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      <ul className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden custom-scrollbar divide-y divide-line">
        {history.map((event) => {
          const Icon = ALARM_ICONS[getAlarmSource(event.sourceId).icon];
          return (
            <li key={event.id} className="flex items-start gap-3 px-5 py-3">
              <Icon className="w-3.5 h-3.5 mt-0.5 shrink-0 text-warn" />
              <div className="flex-1 min-w-0">
                <p className="text-base text-fg">{event.title}</p>
                <p className="mt-0.5 text-base text-fg-muted">{event.body}</p>
              </div>
              <time
                dateTime={event.firedAt}
                className="shrink-0 text-xs font-mono tabnum text-fg-subtle"
              >
                {TIME_FORMAT.format(new Date(event.firedAt))}
              </time>
            </li>
          );
        })}
      </ul>
      <div className="shrink-0 border-t border-line px-5 py-2.5 flex justify-end">
        <button
          type="button"
          onClick={clearAlarmHistory}
          className="rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          Clear history
        </button>
      </div>
    </div>
  );
}
