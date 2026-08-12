'use client';

import { useCallback, useRef, useState } from 'react';
import { ImagePlus, Loader2, X } from 'lucide-react';

import { uploadCommunityMedia } from '@/lib/api';

const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPTED = 'image/png,image/jpeg,image/webp,image/gif';

interface ImageDropzoneProps {
  /** The uploaded image's public URL, or undefined before anything is chosen. */
  value?: string;
  onChange: (url: string | undefined) => void;
  onBusyChange?: (busy: boolean) => void;
}

/**
 * Drag-and-drop (or click) image upload.
 *
 * The upload is a plain fetch, so there is no byte-level progress to report —
 * rather than animate a fake bar, this shows an honest indeterminate state. The
 * size and type are checked here for a fast, clear rejection, and again on the
 * server by sniffing the file's own magic bytes, which is the check that counts.
 */
export default function ImageDropzone({ value, onChange, onBusyChange }: ImageDropzoneProps) {
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | undefined>();
  const inputRef = useRef<HTMLInputElement>(null);

  const setBusy = useCallback(
    (busy: boolean) => {
      setUploading(busy);
      onBusyChange?.(busy);
    },
    [onBusyChange]
  );

  const upload = useCallback(
    async (file: File) => {
      setError(undefined);

      if (!ACCEPTED.split(',').includes(file.type)) {
        setError('PNG, JPEG, WebP and GIF only.');
        return;
      }
      if (file.size > MAX_BYTES) {
        setError('That image is over 5 MB.');
        return;
      }

      setBusy(true);
      try {
        const media = await uploadCommunityMedia(file);
        onChange(media.url);
      } catch {
        setError('The upload failed. Try again.');
      } finally {
        setBusy(false);
      }
    },
    [onChange, setBusy]
  );

  if (value) {
    return (
      <div className="relative overflow-hidden rounded-md border border-line bg-surface-2">
        <img src={value} alt="Selected upload" className="max-h-64 w-full object-contain" />
        <button
          type="button"
          onClick={() => onChange(undefined)}
          aria-label="Remove image"
          className="absolute right-2 top-2 rounded-md border border-line bg-bg/80 p-1 text-fg-muted backdrop-blur-sm transition-colors hover:text-fg"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
        disabled={uploading}
        className={`flex w-full flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-8 transition-colors ${
          dragging
            ? 'border-accent bg-accent-bg'
            : 'border-line bg-surface-2 hover:border-line-strong'
        }`}
      >
        {uploading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-fg-muted" />
            <span className="text-sm text-fg-muted">Uploading…</span>
          </>
        ) : (
          <>
            <ImagePlus className="h-4 w-4 text-fg-subtle" />
            <span className="text-sm text-fg-muted">Drop an image, or click to choose one</span>
            <span className="text-2xs text-fg-subtle">PNG, JPEG, WebP or GIF · up to 5 MB</span>
          </>
        )}
      </button>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void upload(file);
          // Reset so choosing the same file twice still fires a change.
          event.target.value = '';
        }}
      />

      {error && <p className="mt-1.5 text-sm text-down">{error}</p>}
    </div>
  );
}
