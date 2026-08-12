'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import Modal from '@/components/ui/Modal';
import type { CommunityPost, UpdateCommunityPostInput } from '@/lib/api';

import MarkdownField from './MarkdownField';

const MAX_TITLE = 300;
const MAX_CONTENT = 20_000;

const INPUT_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none';

interface EditPostModalProps {
  post: CommunityPost | undefined;
  onClose: () => void;
  onSubmit: (patch: UpdateCommunityPostInput) => Promise<unknown>;
  isSubmitting: boolean;
}

/**
 * Edit your own post.
 *
 * Title, body and ticker only — the post's kind and its image or link are
 * fixed. Turning a text post into a link post after people have voted on it
 * would misrepresent what they voted for; that is a new post, not an edit.
 */
export default function EditPostModal({
  post,
  onClose,
  onSubmit,
  isSubmitting,
}: EditPostModalProps) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [symbol, setSymbol] = useState('');

  useEffect(() => {
    if (!post) return;
    setTitle(post.title ?? '');
    setContent(post.content);
    setSymbol(post.asset_symbol ?? '');
  }, [post]);

  const canSubmit =
    Boolean(post) &&
    content.trim().length > 0 &&
    content.length <= MAX_CONTENT &&
    title.length <= MAX_TITLE &&
    !isSubmitting;

  return (
    <Modal isOpen={Boolean(post)} onClose={onClose} title="Edit post" maxWidth="max-w-2xl">
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!canSubmit) return;
          await onSubmit({
            title: title.trim(),
            content: content.trim(),
            asset_symbol: symbol.trim().toUpperCase(),
          });
        }}
        className="space-y-4 p-4"
      >
        <div>
          <label htmlFor="edit-title" className="label mb-1.5 block">
            Title
          </label>
          <input
            id="edit-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={MAX_TITLE}
            className={INPUT_CLASS}
          />
        </div>

        <MarkdownField
          value={content}
          onChange={setContent}
          label="Post"
          maxLength={MAX_CONTENT}
          rows={8}
          required
        />

        <div>
          <label htmlFor="edit-symbol" className="label mb-1.5 block">
            Ticker
          </label>
          <input
            id="edit-symbol"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
            maxLength={20}
            className={`${INPUT_CLASS} font-mono uppercase`}
          />
        </div>

        <p className="text-sm text-fg-subtle">Edited posts are labelled as such in the feed.</p>

        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line bg-surface px-3 py-1.5 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-base text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save
          </button>
        </div>
      </form>
    </Modal>
  );
}
