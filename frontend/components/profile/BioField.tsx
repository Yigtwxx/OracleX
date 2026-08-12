'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import { MAX_BIO_LENGTH } from '@/lib/social-links';

interface BioFieldProps {
  value: string;
  onSave: (bio: string) => Promise<void>;
  disabled?: boolean;
}

/**
 * The one line a profile gets to say about itself, shown at `/u/{id}`.
 *
 * Capped at 200 characters here, in the API, and in a database CHECK. The
 * counter turns red at the limit and the save button goes dead rather than the
 * text being silently truncated — a sentence cut mid-word is worse than a
 * refused save.
 */
export default function BioField({ value, onSave, disabled }: BioFieldProps) {
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Re-seed when the stored value arrives or changes underneath us.
  useEffect(() => setDraft(value), [value]);

  const dirty = draft !== value;
  const tooLong = draft.length > MAX_BIO_LENGTH;

  const save = async () => {
    setError('');
    setSaving(true);
    try {
      await onSave(draft.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save that.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-1.5">
      <label htmlFor="profile-bio" className="text-sm text-fg-subtle">
        Bio
      </label>
      <textarea
        id="profile-bio"
        rows={3}
        value={draft}
        disabled={disabled || saving}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="A sentence about you. Shown on your public profile."
        className="w-full resize-none rounded-md border border-line bg-surface-2 px-3 py-2 text-base text-fg placeholder:text-fg-subtle focus:border-fg-subtle focus:outline-none disabled:opacity-50"
      />
      <div className="flex items-center justify-between gap-3">
        <span className={`text-sm ${tooLong ? 'text-down' : 'text-fg-subtle'}`}>
          {draft.length} / {MAX_BIO_LENGTH}
        </span>
        {dirty && (
          <button
            type="button"
            onClick={save}
            disabled={saving || tooLong}
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:text-fg disabled:opacity-50"
          >
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Save bio
          </button>
        )}
      </div>
      {error && <p className="text-sm text-down">{error}</p>}
    </div>
  );
}
