'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Ban, Loader2, MoreVertical, User } from 'lucide-react';

import MessageComposer from '@/components/social/MessageComposer';
import EligibilityNotice from '@/components/social/EligibilityNotice';
import { formatDayLabel, groupByDay } from '@/lib/social';
import { dmRefusalReasons, type DmConversation, type DmEligibility } from '@/lib/api';
import { useBlockMember, useMarkRead, useMessages, useSendMessage } from '@/hooks/useSocial';

/**
 * The right pane: one conversation.
 *
 * Polls every three seconds while it is the visible thread. Read state is
 * advanced once per thread per mount rather than on every poll — a write on a
 * three-second timer would be a write every three seconds for a tab left open.
 */
export default function MessageThread({
  conversation,
  viewerId,
  eligibility,
  onBack,
}: {
  conversation: DmConversation;
  viewerId: string;
  eligibility?: DmEligibility;
  onBack?: () => void;
}) {
  const { data: messages, isLoading } = useMessages(conversation.id);
  const send = useSendMessage(conversation.id);
  const markRead = useMarkRead();
  const block = useBlockMember();

  const [refusal, setRefusal] = useState<string[]>([]);
  const [sendError, setSendError] = useState<string>();
  const [menuOpen, setMenuOpen] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const markReadRef = useRef(markRead.mutate);
  markReadRef.current = markRead.mutate;

  // Once per conversation, not once per poll. The ref keeps the effect from
  // re-firing when react-query hands back a new mutate identity.
  useEffect(() => {
    setRefusal([]);
    setSendError(undefined);
    if (conversation.unread_count > 0) markReadRef.current(conversation.id);
  }, [conversation.id, conversation.unread_count]);

  const count = messages?.length ?? 0;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [count, conversation.id]);

  const handleSend = async (body: string) => {
    setSendError(undefined);
    try {
      await send.mutateAsync(body);
      setRefusal([]);
    } catch (error) {
      const reasons = dmRefusalReasons(error);
      if (reasons.length > 0) setRefusal(reasons);
      else setSendError(error instanceof Error ? error.message : 'The message did not send.');
      // Re-thrown so the composer keeps the draft: it only clears on success.
      throw error;
    }
  };

  const peerName = conversation.peer.full_name || 'Anonymous';
  const blocked = refusal.length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-2">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            aria-label="Back to conversations"
            className="rounded-md p-1 text-fg-muted transition-colors hover:text-fg md:hidden"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
        )}

        <Link
          href={`/u/${conversation.peer.id}`}
          className="flex min-w-0 flex-1 items-center gap-2.5 transition-opacity hover:opacity-80"
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
          <span className="truncate text-md font-semibold text-fg">{peerName}</span>
        </Link>

        <div className="relative shrink-0">
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-label="Conversation options"
            aria-expanded={menuOpen}
            className="rounded-md p-1 text-fg-muted transition-colors hover:text-fg"
          >
            <MoreVertical className="h-4 w-4" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full z-20 mt-1 w-44 rounded-lg border border-line bg-surface py-1">
              <button
                type="button"
                onClick={() => {
                  setMenuOpen(false);
                  block.mutate(conversation.peer.id);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-down transition-colors hover:bg-surface-2"
              >
                <Ban className="h-3.5 w-3.5" />
                Block {peerName}
              </button>
            </div>
          )}
        </div>
      </header>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-4">
        {isLoading ? (
          <div className="space-y-3">
            <div className="shimmer h-10 w-2/3 rounded-lg" />
            <div className="shimmer ml-auto h-10 w-1/2 rounded-lg" />
          </div>
        ) : count === 0 ? (
          <p className="mt-8 text-center text-base text-fg-subtle">
            No messages yet. Say something.
          </p>
        ) : (
          groupByDay(messages ?? [], (message) => message.created_at).map((group) => (
            <section key={group.day}>
              {formatDayLabel(group.day) && (
                <div className="my-3 flex items-center gap-3">
                  <span className="h-px flex-1 bg-line" />
                  <span className="text-xs text-fg-subtle">{formatDayLabel(group.day)}</span>
                  <span className="h-px flex-1 bg-line" />
                </div>
              )}
              <ul className="space-y-1.5">
                {group.items.map((message) => {
                  const mine = message.sender_id === viewerId;
                  return (
                    <li
                      key={message.id}
                      className={`flex ${mine ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-[75%] rounded-lg px-3 py-2 ${
                          mine ? 'bg-accent text-white' : 'border border-line bg-surface-2 text-fg'
                        }`}
                      >
                        <p className="whitespace-pre-wrap break-words text-base">{message.body}</p>
                        <time
                          dateTime={message.created_at}
                          className={`mt-0.5 block text-right text-2xs ${
                            mine ? 'text-white/70' : 'text-fg-subtle'
                          }`}
                        >
                          {new Date(message.created_at).toLocaleTimeString(undefined, {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </time>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {blocked ? (
        <div className="shrink-0 border-t border-line p-3">
          <EligibilityNotice eligibility={eligibility} reasons={refusal} />
        </div>
      ) : (
        <MessageComposer
          onSend={handleSend}
          isSending={send.isPending}
          error={sendError}
          disabled={block.isPending}
        />
      )}

      {block.isPending && (
        <p className="flex items-center justify-center gap-1.5 pb-2 text-sm text-fg-subtle">
          <Loader2 className="h-3 w-3 animate-spin" />
          Blocking…
        </p>
      )}
    </div>
  );
}
