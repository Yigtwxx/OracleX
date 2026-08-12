'use client';

import { useEffect, useState } from 'react';
import { Link2, Loader2, Plus, X } from 'lucide-react';

import ProfileCard from '@/components/profile/ProfileCard';
import SocialIconRow from '@/components/profile/SocialIconRow';
import { SocialGlyph } from '@/components/profile/social-icons';
import { useProfile, useUpdateSocialLinks } from '@/hooks/useProfile';
import type { SocialLink, SocialLinkInput } from '@/lib/api';
import {
  MAX_CUSTOM_LABEL_LENGTH,
  MAX_CUSTOM_LINKS,
  PLATFORM_BY_ID,
  SOCIAL_PLATFORMS,
  buildProfileUrl,
  isSafeCustomUrl,
  isValidHandle,
  normaliseHandle,
} from '@/lib/social-links';

interface Draft {
  platform: string;
  handle: string;
  label: string;
  url: string;
}

const CUSTOM = 'custom';

function toDraft(link: SocialLink): Draft {
  return {
    platform: link.platform,
    handle: link.handle ?? '',
    label: link.label ?? '',
    url: link.url ?? '',
  };
}

function isComplete(draft: Draft): boolean {
  if (draft.platform === CUSTOM) {
    return draft.label.trim().length > 0 && isSafeCustomUrl(draft.url);
  }
  return isValidHandle(draft.platform, normaliseHandle(draft.platform, draft.handle));
}

function toPreview(draft: Draft, position: number): SocialLink {
  if (draft.platform === CUSTOM) {
    return {
      platform: CUSTOM,
      handle: null,
      label: draft.label.trim(),
      url: draft.url.trim(),
      position,
    };
  }
  const handle = normaliseHandle(draft.platform, draft.handle);
  return {
    platform: draft.platform,
    handle,
    label: null,
    url: buildProfileUrl(draft.platform, handle) ?? null,
    position,
  };
}

/**
 * Where a user lists the accounts they want other people to find.
 *
 * These are self-declared, and the card says so. The previous occupant of this
 * slot promised OAuth linking it could not do; an unverifiable claim dressed as
 * a verified one would be the same mistake in a new costume, so there is no
 * badge here and none on the public page.
 *
 * The whole set saves in one PUT. Per-link saving would need an id the client
 * has no other use for, for a list that never exceeds sixteen rows.
 */
export default function SocialLinksCard() {
  const { data: profile, isLoading } = useProfile();
  const save = useUpdateSocialLinks();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [error, setError] = useState('');

  const stored = profile?.social_links;

  useEffect(() => {
    setDrafts((stored ?? []).map(toDraft));
  }, [stored]);

  const usedPlatforms = new Set(drafts.filter((d) => d.platform !== CUSTOM).map((d) => d.platform));
  const customCount = drafts.filter((d) => d.platform === CUSTOM).length;
  const available = SOCIAL_PLATFORMS.filter((p) => !usedPlatforms.has(p.id));

  const update = (index: number, patch: Partial<Draft>) =>
    setDrafts((current) => current.map((d, i) => (i === index ? { ...d, ...patch } : d)));

  const remove = (index: number) => setDrafts((current) => current.filter((_, i) => i !== index));

  const add = (platform: string) =>
    setDrafts((current) => [...current, { platform, handle: '', label: '', url: '' }]);

  const preview = drafts.filter(isComplete).map(toPreview);
  const incomplete = drafts.some((draft) => !isComplete(draft));

  const submit = async () => {
    setError('');
    const payload: SocialLinkInput[] = drafts
      .filter(isComplete)
      .map((draft) =>
        draft.platform === CUSTOM
          ? { platform: CUSTOM, label: draft.label.trim(), url: draft.url.trim() }
          : { platform: draft.platform, handle: normaliseHandle(draft.platform, draft.handle) }
      );

    try {
      await save.mutateAsync(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Your links could not be saved.');
    }
  };

  return (
    <ProfileCard title="Social links" icon={Link2}>
      <p className="mb-3 text-sm text-fg-subtle">
        Shown on your public profile. These are not verified — anyone reading them is taking your
        word for it.
      </p>

      {isLoading ? (
        <div className="shimmer h-10 w-full rounded-md" />
      ) : (
        <>
          <ul className="space-y-2">
            {drafts.map((draft, index) => {
              const spec = PLATFORM_BY_ID[draft.platform];
              // Only flag a row the user has actually started filling in;
              // an untouched new row is not an error yet.
              const bad =
                draft.platform === CUSTOM
                  ? draft.url.length > 0 && !isSafeCustomUrl(draft.url)
                  : draft.handle.length > 0 && !isComplete(draft);

              return (
                <li
                  key={`${draft.platform}-${index}`}
                  className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-2.5 py-2"
                >
                  <SocialGlyph
                    platform={draft.platform}
                    className="h-4 w-4 shrink-0 text-fg-muted"
                  />

                  {draft.platform === CUSTOM ? (
                    <>
                      <input
                        value={draft.label}
                        maxLength={MAX_CUSTOM_LABEL_LENGTH}
                        onChange={(e) => update(index, { label: e.target.value })}
                        placeholder="Label"
                        aria-label="Link label"
                        className="w-28 shrink-0 rounded border border-line bg-bg px-2 py-1 text-base text-fg placeholder:text-fg-subtle focus:outline-none"
                      />
                      <input
                        value={draft.url}
                        onChange={(e) => update(index, { url: e.target.value })}
                        placeholder="https://example.com"
                        aria-label="Link URL"
                        className={`min-w-0 flex-1 rounded border bg-bg px-2 py-1 text-base text-fg placeholder:text-fg-subtle focus:outline-none ${
                          bad ? 'border-down' : 'border-line'
                        }`}
                      />
                    </>
                  ) : (
                    <>
                      <span className="w-24 shrink-0 truncate text-base text-fg-muted">
                        {spec?.label ?? draft.platform}
                      </span>
                      <input
                        value={draft.handle}
                        onChange={(e) => update(index, { handle: e.target.value })}
                        placeholder={spec?.placeholder ?? 'username'}
                        aria-label={`${spec?.label ?? draft.platform} username`}
                        className={`min-w-0 flex-1 rounded border bg-bg px-2 py-1 text-base text-fg placeholder:text-fg-subtle focus:outline-none ${
                          bad ? 'border-down' : 'border-line'
                        }`}
                      />
                    </>
                  )}

                  <button
                    type="button"
                    onClick={() => remove(index)}
                    aria-label="Remove this link"
                    className="shrink-0 rounded p-1 text-fg-subtle transition-colors hover:text-down"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {available.map((platform) => (
              <button
                key={platform.id}
                type="button"
                onClick={() => add(platform.id)}
                className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:text-fg"
              >
                <Plus className="h-3 w-3" />
                {platform.label}
              </button>
            ))}
            {customCount < MAX_CUSTOM_LINKS && (
              <button
                type="button"
                onClick={() => add(CUSTOM)}
                className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-sm text-fg-muted transition-colors hover:text-fg"
              >
                <Plus className="h-3 w-3" />
                Website
              </button>
            )}
          </div>

          {preview.length > 0 && (
            <div className="mt-4 border-t border-line pt-3">
              <p className="mb-2 text-sm text-fg-subtle">How this looks to other people</p>
              <SocialIconRow links={preview} />
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={save.isPending || incomplete}
              className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-base text-fg-muted transition-colors hover:text-fg disabled:opacity-50"
            >
              {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Save links
            </button>
            {incomplete && (
              <span className="text-sm text-fg-subtle">
                Finish or remove the unfilled rows first.
              </span>
            )}
          </div>
        </>
      )}

      {error && <p className="mt-2 text-sm text-down">{error}</p>}
    </ProfileCard>
  );
}
