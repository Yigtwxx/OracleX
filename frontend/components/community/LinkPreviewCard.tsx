'use client';

import { useState } from 'react';
import { ExternalLink, Link2 } from 'lucide-react';

import type { CommunityLinkPreview } from '@/lib/api';

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/**
 * The card on a link post.
 *
 * The OpenGraph fields are read off the post row, which the backend filled in
 * once at create time — rendering the feed never touches the linked server.
 * A post whose preview could not be fetched still has a URL, so the no-image,
 * no-title layout is the normal case rather than an error state.
 */
export default function LinkPreviewCard({ link }: { link: CommunityLinkPreview }) {
  const [imageFailed, setImageFailed] = useState(false);
  const host = link.site_name || hostOf(link.url);
  const showImage = Boolean(link.image_url) && !imageFailed;

  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      onClick={(event) => event.stopPropagation()}
      className="group flex overflow-hidden rounded-md border border-line bg-surface-2 transition-colors hover:border-line-strong"
    >
      <div className="flex w-24 shrink-0 items-center justify-center overflow-hidden border-r border-line bg-surface sm:w-32">
        {showImage ? (
          <img
            src={link.image_url as string}
            alt=""
            loading="lazy"
            onError={() => setImageFailed(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <Link2 className="h-4 w-4 text-fg-subtle" />
        )}
      </div>

      <div className="min-w-0 flex-1 px-3 py-2.5">
        <div className="flex items-center gap-1.5 text-2xs uppercase tracking-wide text-fg-subtle">
          <span className="truncate">{host}</span>
          <ExternalLink className="h-3 w-3 shrink-0" />
        </div>

        <p className="mt-1 line-clamp-2 text-base font-medium text-fg group-hover:text-accent">
          {link.title || link.url}
        </p>

        {link.description && (
          <p className="mt-1 line-clamp-2 text-sm text-fg-subtle">{link.description}</p>
        )}
      </div>
    </a>
  );
}
