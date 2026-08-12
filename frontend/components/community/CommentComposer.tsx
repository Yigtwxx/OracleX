'use client';

import { useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';

const MAX_LENGTH = 10_000;

interface CommentComposerProps {
  onSubmit: (content: string) => Promise<unknown>;
  onCancel?: () => void;
  isSubmitting: boolean;
  placeholder?: string;
  submitLabel?: string;
  initialValue?: string;
  /** Reply and edit boxes appear on demand and should take focus. */
  autoFocus?: boolean;
}

export default function CommentComposer({
  onSubmit,
  onCancel,
  isSubmitting,
  placeholder = 'Add a comment',
  submitLabel = 'Comment',
  initialValue = '',
  autoFocus = false,
}: CommentComposerProps) {
  const [value, setValue] = useState(initialValue);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus();
  }, [autoFocus]);

  const canSubmit = value.trim().length > 0 && value.length <= MAX_LENGTH && !isSubmitting;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        await onSubmit(value.trim());
        setValue('');
      }}
      className="space-y-2"
    >
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        rows={3}
        maxLength={MAX_LENGTH}
        // Ctrl/Cmd+Enter submits: the same chord every other comment box uses.
        onKeyDown={(event) => {
          if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && canSubmit) {
            event.preventDefault();
            void onSubmit(value.trim()).then(() => setValue(''));
          }
        }}
        className="w-full resize-y rounded-md border border-line bg-surface-2 px-2.5 py-2 text-base text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none"
      />

      <div className="flex items-center justify-end gap-2">
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-2.5 py-1 text-sm text-fg-muted transition-colors hover:text-fg"
          >
            Cancel
          </button>
        )}
        <button
          type="submit"
          disabled={!canSubmit}
          className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1 text-sm text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting && <Loader2 className="h-3 w-3 animate-spin" />}
          {submitLabel}
        </button>
      </div>
    </form>
  );
}
