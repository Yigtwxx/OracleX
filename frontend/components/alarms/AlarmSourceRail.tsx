'use client';

import type { ReactNode } from 'react';
import { Bell, Clock, Mail, Search } from 'lucide-react';
import { ALARM_GROUPS, ALARM_SOURCES } from '@/lib/alarms/registry';
import type { AlarmSourceId } from '@/lib/alarms/types';
import { ALARM_ICONS } from './icons';
import { INPUT_CLASS } from './controls';

export type AlarmView =
  | { kind: 'source'; sourceId: AlarmSourceId }
  | { kind: 'list' }
  | { kind: 'history' }
  | { kind: 'email' };

export default function AlarmSourceRail({
  view,
  onSelect,
  query,
  onQueryChange,
  alarmCount,
  historyCount,
  emailConfirmed,
}: {
  view: AlarmView;
  onSelect: (view: AlarmView) => void;
  query: string;
  onQueryChange: (query: string) => void;
  alarmCount: number;
  historyCount: number;
  emailConfirmed: boolean;
}) {
  const needle = query.trim().toLocaleLowerCase('tr');
  const matches = ALARM_SOURCES.filter(
    (source) =>
      needle.length === 0 ||
      source.label.toLocaleLowerCase('tr').includes(needle) ||
      source.description.toLocaleLowerCase('tr').includes(needle)
  );

  return (
    <div className="flex flex-col h-full">
      <div className="shrink-0 p-3 border-b border-line">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-fg-subtle pointer-events-none" />
          <input
            type="search"
            aria-label="Search sources"
            placeholder="Search sources"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            className={`${INPUT_CLASS} pl-8`}
          />
        </div>
      </div>

      <nav className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden custom-scrollbar py-2">
        {ALARM_GROUPS.map((group) => {
          const sources = matches.filter((source) => source.group === group.id);
          if (sources.length === 0) return null;

          return (
            <div key={group.id} className="mb-2">
              <p className="label px-3 py-1.5">{group.label}</p>
              <ul>
                {sources.map((source) => {
                  const Icon = ALARM_ICONS[source.icon];
                  const active = view.kind === 'source' && view.sourceId === source.id;
                  return (
                    <li key={source.id}>
                      <button
                        type="button"
                        aria-current={active ? 'true' : undefined}
                        onClick={() => onSelect({ kind: 'source', sourceId: source.id })}
                        className={`w-full flex items-center gap-2 px-3 py-1.5 text-base text-left transition-colors ${
                          active
                            ? 'bg-accent-bg text-accent'
                            : 'text-fg-muted hover:bg-surface-2 hover:text-fg'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5 shrink-0" />
                        <span className="truncate">{source.label}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}

        {matches.length === 0 && (
          <p className="px-3 py-2 text-base text-fg-subtle">No matching source.</p>
        )}
      </nav>

      <div className="shrink-0 border-t border-line py-1">
        <RailEntry
          icon={Bell}
          label="My Alarms"
          trailing={alarmCount}
          active={view.kind === 'list'}
          onClick={() => onSelect({ kind: 'list' })}
        />
        <RailEntry
          icon={Clock}
          label="History"
          trailing={historyCount}
          active={view.kind === 'history'}
          onClick={() => onSelect({ kind: 'history' })}
        />
        <RailEntry
          icon={Mail}
          label="Email Alerts"
          // A dot, not a number: there is exactly one address or none, and "1"
          // in the column that counts alarms would read as one alarm.
          trailing={
            <span
              aria-hidden
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                emailConfirmed ? 'bg-up' : 'bg-fg-subtle/40'
              }`}
            />
          }
          srTrailing={emailConfirmed ? 'Address confirmed' : 'No address'}
          active={view.kind === 'email'}
          onClick={() => onSelect({ kind: 'email' })}
        />
      </div>
    </div>
  );
}

function RailEntry({
  icon: Icon,
  label,
  trailing,
  srTrailing,
  active,
  onClick,
}: {
  icon: typeof Bell;
  label: string;
  trailing: ReactNode;
  /** What a screen reader hears when `trailing` is purely visual. */
  srTrailing?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-current={active ? 'true' : undefined}
      onClick={onClick}
      className={`w-full flex items-center gap-2 px-3 py-2 text-base transition-colors ${
        active ? 'bg-accent-bg text-accent' : 'text-fg-muted hover:bg-surface-2 hover:text-fg'
      }`}
    >
      <Icon className="w-3.5 h-3.5 shrink-0" />
      <span className="flex-1 text-left">{label}</span>
      {srTrailing && <span className="sr-only">{srTrailing}</span>}
      <span className="text-xs font-mono tabnum text-fg-subtle">{trailing}</span>
    </button>
  );
}
