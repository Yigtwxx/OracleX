'use client';

import { MessageSquare, User } from 'lucide-react';

import { relativeTime } from '@/components/community/PostMeta';
import { formatUnread, previewText } from '@/lib/social';
import type { DmConversation } from '@/lib/api';

/**
 * The left pane: every thread this member is in.
 *
 * Rendered from `dm_inbox`, which already sorts newest-first and carries the
 * unread count, so this file only decides what it looks like.
 */
export default function ConversationList({
  conversations,
  selectedId,
  onSelect,
  isLoading,
}: {
  conversations: DmConversation[];
  selectedId?: string;
  onSelect: (conversationId: string) => void;
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-2 p-3">
        {[0, 1, 2].map((row) => (
          <div key={row} className="shimmer h-14 rounded-md" />
        ))}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <MessageSquare className="h-5 w-5 text-fg-subtle" />
        <p className="text-base text-fg-muted">No conversations yet</p>
        <p className="text-sm text-fg-subtle">
          Open somebody&apos;s profile from the Community board and press Message.
        </p>
      </div>
    );
  }

  return (
    <ul className="custom-scrollbar h-full overflow-y-auto overflow-x-hidden">
      {conversations.map((conversation) => {
        const isSelected = conversation.id === selectedId;
        const unread = formatUnread(conversation.unread_count);
        const name = conversation.peer.full_name || 'Anonymous';

        return (
          <li key={conversation.id}>
            <button
              type="button"
              onClick={() => onSelect(conversation.id)}
              aria-current={isSelected ? 'true' : undefined}
              className={`flex w-full items-center gap-2.5 border-b border-line px-3 py-2.5 text-left transition-colors ${
                isSelected ? 'bg-surface-2' : 'hover:bg-surface-2'
              }`}
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full border border-line bg-surface-2">
                {conversation.peer.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={conversation.peer.avatar_url}
                    alt=""
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <User className="h-3.5 w-3.5 text-fg-subtle" />
                )}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span
                    className={`truncate text-base ${unread ? 'font-semibold text-fg' : 'text-fg-muted'}`}
                  >
                    {name}
                  </span>
                  {conversation.last_message_at && (
                    <time
                      dateTime={conversation.last_message_at}
                      className="shrink-0 text-xs text-fg-subtle"
                    >
                      {relativeTime(conversation.last_message_at)}
                    </time>
                  )}
                </div>
                <p className={`truncate text-sm ${unread ? 'text-fg-muted' : 'text-fg-subtle'}`}>
                  {previewText(conversation.last_message?.body)}
                </p>
              </div>

              {unread && (
                <span className="shrink-0 rounded-full bg-accent px-1.5 py-0.5 text-2xs font-semibold text-white">
                  {unread}
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
