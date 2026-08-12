'use client';

import { useRef, useState } from 'react';
import { Loader2, Trash2, Upload, User } from 'lucide-react';

import { useDeleteAvatar, useUploadAvatar } from '@/hooks/useProfile';

/** Mirrors AVATAR_MAX_BYTES in routers/profile.py, so the user hears about it first. */
const MAX_BYTES = 2 * 1024 * 1024;
const ACCEPT = 'image/png,image/jpeg,image/webp,image/gif';

interface AvatarFieldProps {
  url?: string;
  /** Falls back to a letter when there is no photo. */
  displayName: string;
}

/**
 * The profile photo.
 *
 * This used to be a text box you pasted a URL into, which meant the photo was
 * hosted by whoever you borrowed it from and broke when they took it down. It
 * is now a real upload: the file goes to the `profile-avatars` bucket through
 * the backend, which decides the type from the file's magic bytes rather than
 * its name.
 */
export default function AvatarField({ url, displayName }: AvatarFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const upload = useUploadAvatar();
  const remove = useDeleteAvatar();

  const busy = upload.isPending || remove.isPending;

  const handleFile = async (file: File | undefined) => {
    setError('');
    if (!file) return;

    // Checked here as well as on the server: a 2 MB round-trip to be told no is
    // a poor way to learn the limit.
    if (file.size > MAX_BYTES) {
      setError('Images must be 2 MB or smaller.');
      return;
    }
    if (!file.type.startsWith('image/')) {
      setError('Choose a PNG, JPEG, WebP or GIF.');
      return;
    }

    try {
      await upload.mutateAsync(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not upload that image.');
    }
  };

  const handleRemove = async () => {
    setError('');
    try {
      await remove.mutateAsync();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove the photo.');
    }
  };

  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          handleFile(event.dataTransfer.files?.[0]);
        }}
        aria-label="Change profile photo"
        className={`relative h-16 w-16 shrink-0 overflow-hidden rounded-full border bg-surface-2 transition-colors ${
          dragging ? 'border-accent' : 'border-line hover:border-line-strong'
        } disabled:opacity-50`}
      >
        {url ? (
          /* A Supabase Storage URL on a host next.config.js does not allow;
             next/image would need a domain allowlist for no gain at 64px. */
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt="" className="h-full w-full object-cover" />
        ) : (
          <span className="flex h-full w-full items-center justify-center">
            {displayName ? (
              <span className="text-lg font-semibold text-fg-muted">
                {displayName.charAt(0).toUpperCase()}
              </span>
            ) : (
              <User className="h-5 w-5 text-fg-subtle" />
            )}
          </span>
        )}
        {busy && (
          <span className="absolute inset-0 flex items-center justify-center bg-bg/70">
            <Loader2 className="h-4 w-4 animate-spin text-fg-muted" />
          </span>
        )}
      </button>

      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
          >
            <Upload className="h-3.5 w-3.5" />
            {url ? 'Replace' : 'Upload photo'}
          </button>
          {url && (
            <button
              type="button"
              disabled={busy}
              onClick={handleRemove}
              className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:border-down hover:text-down disabled:opacity-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Remove
            </button>
          )}
        </div>
        <p className={`text-sm ${error ? 'text-down' : 'text-fg-subtle'}`}>
          {error || 'PNG, JPEG, WebP or GIF. Up to 2 MB.'}
        </p>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(event) => {
          handleFile(event.target.files?.[0]);
          // Reset so picking the same file twice still fires a change event.
          event.target.value = '';
        }}
      />
    </div>
  );
}
