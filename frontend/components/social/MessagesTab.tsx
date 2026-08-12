'use client';

import { useState } from 'react';

import ConversationList from '@/components/social/ConversationList';
import EligibilityNotice from '@/components/social/EligibilityNotice';
import MessageThread from '@/components/social/MessageThread';
import { useConversations, useDmEligibility } from '@/hooks/useSocial';

/**
 * The inbox and the open thread.
 *
 * Two panes above `md`. Below it there is not room for both, so the list is
 * full-width and selecting a conversation swaps to the thread with a back
 * button — a 288px list beside a thread on a phone leaves neither usable.
 */
export default function MessagesTab({ viewerId }: { viewerId: string }) {
  const { data: conversations, isLoading, isError, refetch } = useConversations();
  const { data: eligibility } = useDmEligibility();
  const [selectedId, setSelectedId] = useState<string>();

  const rows = conversations ?? [];
  const selected = rows.find((row) => row.id === selectedId);

  // Rendered here rather than as a toast, and never as an empty inbox: "you
  // have no conversations" is a claim, and this is the case where we do not
  // know. The server log names what actually failed.
  if (isError && rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <p className="text-base text-fg-muted">Messages are unavailable right now.</p>
          <p className="mt-1 text-sm text-fg-subtle">
            The server could not load your conversations.
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-3 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Shown above the panes rather than in place of them: someone who cannot
          start new conversations can still read and reply in existing ones, so
          replacing the whole tab would hide threads they are part of. */}
      {eligibility && !eligibility.can_send && (
        <div className="shrink-0 border-b border-line p-3">
          <EligibilityNotice eligibility={eligibility} />
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div
          className={`w-full shrink-0 border-r border-line md:w-72 ${
            selected ? 'hidden md:block' : 'block'
          }`}
        >
          <ConversationList
            conversations={rows}
            selectedId={selectedId}
            onSelect={setSelectedId}
            isLoading={isLoading}
          />
        </div>

        <div className={`min-w-0 flex-1 ${selected ? 'block' : 'hidden md:block'}`}>
          {selected ? (
            <MessageThread
              // Keyed so switching threads remounts rather than carrying the
              // previous conversation's scroll position and refusal state over.
              key={selected.id}
              conversation={selected}
              viewerId={viewerId}
              eligibility={eligibility}
              onBack={() => setSelectedId(undefined)}
            />
          ) : (
            <div className="flex h-full items-center justify-center p-6">
              <p className="text-base text-fg-subtle">Pick a conversation.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
