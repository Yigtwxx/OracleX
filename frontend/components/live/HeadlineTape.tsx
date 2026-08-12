'use client';

import { formatDistanceToNow } from 'date-fns';
import type { LiveTapeItem } from '@/lib/api';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';

interface HeadlineTapeProps {
  items: LiveTapeItem[];
  isLoading: boolean;
  /** The news cache has not filled yet — distinct from a genuinely quiet tape. */
  warming: boolean;
}

export default function HeadlineTape({ items, isLoading, warming }: HeadlineTapeProps) {
  if (isLoading) return <PanelSkeleton />;

  return (
    <Panel
      title="Tape"
      action={
        <span className="flex items-center gap-1.5 text-xs text-fg-subtle">
          <span className="w-1.5 h-1.5 rounded-full bg-up live-indicator" />
          Live
        </span>
      }
      footnote="Wire headlines filtered to central banks, policy and macro prints"
    >
      {items.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <p className="text-base text-fg-muted">
            {warming ? 'Waiting for the first news pass.' : 'Nothing macro on the wire yet.'}
          </p>
          <p className="mt-1 text-xs text-fg-subtle">
            {warming
              ? 'The feed fills within a couple of minutes of startup.'
              : 'Headlines appear here as they cross.'}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-line">
          {items.map((item) => (
            <a
              key={item.id}
              href={item.url ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
              className="block px-4 py-2 hover:bg-surface-2 transition-colors"
            >
              <div className="flex items-baseline gap-2">
                <span className="text-2xs font-mono tabnum text-fg-subtle shrink-0">
                  {formatDistanceToNow(new Date(item.published_at), { addSuffix: false })}
                </span>
                <span className="text-sm text-fg line-clamp-2">{item.text}</span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5">
                <span className="text-2xs text-fg-subtle">{item.source}</span>
                {item.tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-1 py-px rounded bg-surface-2 text-2xs uppercase tracking-wide text-fg-subtle"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </a>
          ))}
        </div>
      )}
    </Panel>
  );
}
