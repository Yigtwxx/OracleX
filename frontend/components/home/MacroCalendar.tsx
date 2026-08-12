import { MacroEvent } from '@/lib/api';
import { AlertCircle } from 'lucide-react';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';

interface MacroCalendarProps {
  data: MacroEvent[];
  isLoading: boolean;
  isError: boolean;
}

/** Input format is "MM-DD-YYYY". */
function formatDate(dateStr: string): string {
  if (!dateStr) return '';
  const [m, d, y] = dateStr.split('-');
  const date = new Date(Number(y), Number(m) - 1, Number(d));
  if (Number.isNaN(date.getTime())) return dateStr;
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

export default function MacroCalendar({ data, isLoading, isError }: MacroCalendarProps) {
  if (isLoading) return <PanelSkeleton />;

  return (
    <Panel
      title="Macro Calendar (US)"
      footnote="Upcoming releases only · Filled dot = high impact · Hollow dot = medium impact"
    >
      {/* A failed feed is not a quiet week — the two must not look the same. */}
      {isError ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          <span className="text-base">Calendar unavailable</span>
        </div>
      ) : data.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          {/* Past releases are filtered out, so an empty list late in the week
              means nothing is left — not that the week was quiet. */}
          <span className="text-base">No further events this week</span>
        </div>
      ) : (
        <table className="w-full text-left border-collapse">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr>
              <th className="label px-4 py-1.5">Date</th>
              <th className="label px-4 py-1.5">Event</th>
              <th className="label px-4 py-1.5 text-right">Fcst</th>
              <th className="label px-4 py-1.5 text-right">Prev</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data.map((event, idx) => {
              const isHigh = event.impact === 'High';
              return (
                <tr key={idx} className="hover:bg-surface-2 transition-colors">
                  <td className="px-4 py-2 whitespace-nowrap">
                    <div className="text-base text-fg-muted">{formatDate(event.date)}</div>
                    <div className="text-xs font-mono tabnum text-fg-subtle">{event.time}</div>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                          isHigh ? 'bg-warn' : 'border border-fg-subtle'
                        }`}
                      />
                      <span className={`text-base ${isHigh ? 'text-fg' : 'text-fg-muted'}`}>
                        {event.title}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right text-base font-mono tabnum text-fg-muted">
                    {event.forecast || '–'}
                  </td>
                  <td className="px-4 py-2 text-right text-base font-mono tabnum text-fg-subtle">
                    {event.previous || '–'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
