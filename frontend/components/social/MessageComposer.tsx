'use client';

import { useState, type KeyboardEvent } from 'react';
import { Loader2, SendHorizontal } from 'lucide-react';

import { MAX_MESSAGE_LENGTH } from '@/lib/social';

/**
 * The write box at the foot of a thread.
 *
 * Enter sends and Shift+Enter breaks the line, which is what every messenger
 * does; a Send button is kept anyway because the keyboard convention is
 * invisible and touch has no Enter key worth reaching for.
 */
export default function MessageComposer({
  onSend,
  disabled = false,
  isSending = false,
  error,
}: {
  onSend: (body: string) => Promise<void>;
  disabled?: boolean;
  isSending?: boolean;
  error?: string;
}) {
  const [draft, setDraft] = useState('');

  const trimmed = draft.trim();
  const tooLong = draft.length > MAX_MESSAGE_LENGTH;
  const canSend = trimmed.length > 0 && !tooLong && !disabled && !isSending;

  const submit = async () => {
    if (!canSend) return;
    // Cleared only after the send resolves. Clearing optimistically loses what
    // the user typed when the request fails, and a failed send is exactly when
    // they most want the text back.
    await onSend(trimmed);
    setDraft('');
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <div className="shrink-0 border-t border-line bg-surface p-3">
      {error && <p className="mb-2 text-sm text-down">{error}</p>}
      <div className="flex items-end gap-2">
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={1}
          aria-label="Message"
          placeholder={disabled ? 'You cannot send messages here' : 'Write a message…'}
          className="custom-scrollbar max-h-32 min-h-[2.25rem] flex-1 resize-y rounded-md border border-line bg-bg px-3 py-2 text-base text-fg placeholder:text-fg-subtle focus:border-line-strong focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!canSend}
          aria-label="Send message"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {isSending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <SendHorizontal className="h-4 w-4" />
          )}
        </button>
      </div>

      {/* Only once it starts to matter: a counter under every empty box is
          noise, and the limit is far past a normal message. */}
      {draft.length > MAX_MESSAGE_LENGTH * 0.9 && (
        <p className={`mt-1 text-right text-sm ${tooLong ? 'text-down' : 'text-fg-subtle'}`}>
          {draft.length} / {MAX_MESSAGE_LENGTH}
        </p>
      )}
    </div>
  );
}
