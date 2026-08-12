'use client';

import { useCallback, useEffect, useState } from 'react';
import { FileText, ImageIcon, Link2, Loader2 } from 'lucide-react';

import Modal from '@/components/ui/Modal';
import LinkPreviewCard from '@/components/community/LinkPreviewCard';
import { fetchCommunityLinkPreview } from '@/lib/api';
import type {
  CommunityLinkPreview,
  CommunityPostKind,
  CommunityPostType,
  CreateCommunityPostInput,
} from '@/lib/api';

import ImageDropzone from './ImageDropzone';
import MarkdownField from './MarkdownField';

const MAX_TITLE = 300;
const MAX_CONTENT = 20_000;

const KINDS: { key: CommunityPostKind; label: string; icon: typeof FileText }[] = [
  { key: 'text', label: 'Text', icon: FileText },
  { key: 'image', label: 'Image', icon: ImageIcon },
  { key: 'link', label: 'Link', icon: Link2 },
];

const TYPES: CommunityPostType[] = ['thought', 'question', 'analysis'];

const INPUT_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none';

interface CreatePostModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (input: CreateCommunityPostInput) => Promise<unknown>;
  isSubmitting: boolean;
}

export default function CreatePostModal({
  isOpen,
  onClose,
  onSubmit,
  isSubmitting,
}: CreatePostModalProps) {
  const [kind, setKind] = useState<CommunityPostKind>('text');
  const [type, setType] = useState<CommunityPostType>('thought');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [symbol, setSymbol] = useState('');
  const [imageUrl, setImageUrl] = useState<string | undefined>();
  const [uploading, setUploading] = useState(false);

  const [linkUrl, setLinkUrl] = useState('');
  const [linkPreview, setLinkPreview] = useState<CommunityLinkPreview | undefined>();
  const [previewing, setPreviewing] = useState(false);
  const [linkError, setLinkError] = useState<string | undefined>();

  const reset = useCallback(() => {
    setKind('text');
    setType('thought');
    setTitle('');
    setContent('');
    setSymbol('');
    setImageUrl(undefined);
    setLinkUrl('');
    setLinkPreview(undefined);
    setLinkError(undefined);
  }, []);

  // Clearing on open rather than on close: a failed submit leaves the dialog up,
  // and wiping a long post out from under someone is unforgivable.
  useEffect(() => {
    if (isOpen) reset();
  }, [isOpen, reset]);

  const loadPreview = useCallback(async () => {
    if (!linkUrl.trim()) return;
    setPreviewing(true);
    setLinkError(undefined);
    try {
      setLinkPreview(await fetchCommunityLinkPreview(linkUrl.trim()));
    } catch {
      setLinkPreview(undefined);
      setLinkError('Could not read that page. You can still post the link.');
    } finally {
      setPreviewing(false);
    }
  }, [linkUrl]);

  const contentTooLong = content.length > MAX_CONTENT;
  const canSubmit =
    content.trim().length > 0 &&
    !contentTooLong &&
    title.length <= MAX_TITLE &&
    !isSubmitting &&
    !uploading &&
    (kind !== 'image' || Boolean(imageUrl)) &&
    (kind !== 'link' || linkUrl.trim().length > 0);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;

    await onSubmit({
      type,
      post_kind: kind,
      content: content.trim(),
      title: title.trim() || undefined,
      asset_symbol: symbol.trim().toUpperCase() || undefined,
      image_url: kind === 'image' ? imageUrl : undefined,
      link_url: kind === 'link' ? linkUrl.trim() : undefined,
    });
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="New post" maxWidth="max-w-2xl">
      <form onSubmit={handleSubmit} className="space-y-4 p-4">
        {/* Kind decides which payload field appears below. */}
        <div role="group" aria-label="Post kind" className="flex gap-0.5">
          {KINDS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => setKind(key)}
              aria-pressed={kind === key}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                kind === key ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div>
          <span className="label mb-1.5 block">Flair</span>
          <div className="flex gap-0.5">
            {TYPES.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setType(value)}
                aria-pressed={type === value}
                className={`rounded-md px-3 py-1 text-sm capitalize transition-colors ${
                  type === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
                }`}
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label htmlFor="post-title" className="label mb-1.5 block">
            Title <span className="normal-case text-fg-subtle">(optional)</span>
          </label>
          <input
            id="post-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={MAX_TITLE}
            placeholder="What is the one-line version?"
            className={INPUT_CLASS}
          />
        </div>

        {kind === 'image' && (
          <div>
            <span className="label mb-1.5 block">Image</span>
            <ImageDropzone value={imageUrl} onChange={setImageUrl} onBusyChange={setUploading} />
          </div>
        )}

        {kind === 'link' && (
          <div>
            <label htmlFor="post-link" className="label mb-1.5 block">
              Link
            </label>
            <div className="flex gap-2">
              <input
                id="post-link"
                value={linkUrl}
                onChange={(event) => {
                  setLinkUrl(event.target.value);
                  setLinkPreview(undefined);
                }}
                onBlur={() => void loadPreview()}
                placeholder="https://…"
                className={INPUT_CLASS}
              />
              <button
                type="button"
                onClick={() => void loadPreview()}
                disabled={previewing || !linkUrl.trim()}
                className="shrink-0 rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
              >
                {previewing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Preview'}
              </button>
            </div>

            {linkError && <p className="mt-1.5 text-sm text-warn">{linkError}</p>}
            {linkPreview && (
              <div className="mt-2">
                <LinkPreviewCard link={linkPreview} />
              </div>
            )}
          </div>
        )}

        <MarkdownField
          value={content}
          onChange={setContent}
          label={kind === 'text' ? 'Post' : 'Say something about it'}
          placeholder={
            kind === 'text'
              ? 'What are you seeing, and what would change your mind?'
              : 'Add the context — why does this matter?'
          }
          maxLength={MAX_CONTENT}
          rows={kind === 'text' ? 8 : 4}
          required
        />

        <div>
          <label htmlFor="post-symbol" className="label mb-1.5 block">
            Ticker <span className="normal-case text-fg-subtle">(optional)</span>
          </label>
          <input
            id="post-symbol"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value.toUpperCase())}
            maxLength={20}
            placeholder="BTC, NVDA, …"
            className={`${INPUT_CLASS} font-mono uppercase`}
          />
        </div>

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
            Post
          </button>
        </div>
      </form>
    </Modal>
  );
}
