'use client';

import { Bell, BellOff, Trash2 } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { getAlarmSource } from '@/lib/alarms/registry';
import { describeAlarm } from '@/lib/alarms/describe';
import { ALARM_ICONS } from './icons';

export default function AlarmList() {
  const alarms = useStore((state) => state.alarms);
  const toggleAlarmEnabled = useStore((state) => state.toggleAlarmEnabled);
  const removeAlarm = useStore((state) => state.removeAlarm);

  if (alarms.length === 0) {
    return (
      <EmptyState
        title="No alarms yet"
        body="Pick a source on the left and set up your first alarm."
      />
    );
  }

  return (
    <ul className="divide-y divide-line">
      {alarms.map((alarm) => {
        const source = getAlarmSource(alarm.sourceId);
        const Icon = ALARM_ICONS[source.icon];
        // A spent one-shot is shown as spent rather than merely "off": the user
        // switched nothing, it fired and retired itself.
        const spent = alarm.repeat === 'once' && alarm.triggerCount > 0;

        return (
          <li key={alarm.id} className="flex items-start gap-3 px-5 py-3">
            <Icon
              className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${
                alarm.enabled ? 'text-fg-muted' : 'text-fg-subtle'
              }`}
            />
            <div className="flex-1 min-w-0">
              <p className={`text-base ${alarm.enabled ? 'text-fg' : 'text-fg-subtle'}`}>
                {describeAlarm(alarm)}
              </p>
              <p className="mt-0.5 text-xs text-fg-subtle">
                {spent ? 'Fired — will not notify again' : alarm.enabled ? 'Watching' : 'Paused'}
                {alarm.triggerCount > 0 && ` · ${alarm.triggerCount}×`}
              </p>
            </div>
            <div className="flex items-center gap-0.5 shrink-0">
              <button
                type="button"
                onClick={() => toggleAlarmEnabled(alarm.id)}
                aria-label={alarm.enabled ? 'Pause alarm' : 'Resume alarm'}
                title={alarm.enabled ? 'Pause' : 'Resume'}
                className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-2 transition-colors"
              >
                {alarm.enabled ? (
                  <Bell className="w-3.5 h-3.5" />
                ) : (
                  <BellOff className="w-3.5 h-3.5" />
                )}
              </button>
              <button
                type="button"
                onClick={() => removeAlarm(alarm.id)}
                aria-label="Delete alarm"
                title="Delete"
                className="p-1.5 rounded-md text-fg-muted hover:text-down hover:bg-surface-2 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-1.5 px-8 text-center">
      <p className="text-md text-fg-muted">{title}</p>
      <p className="text-base text-fg-subtle">{body}</p>
    </div>
  );
}
