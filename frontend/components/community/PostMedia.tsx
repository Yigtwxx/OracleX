'use client';

import { useState } from 'react';
import { ImageOff, Maximize2 } from 'lucide-react';

interface PostMediaProps {
  src: string;
  alt: string;
  /** In the feed the image is capped; on the detail page it runs full height. */
  compact?: boolean;
}

/**
 * The image on an image post.
 *
 * Plain `<img>` rather than `next/image`: this codebase has no `images` config
 * and uses no next/image anywhere, and adding remotePatterns for the Supabase
 * storage host to optimise a secondary tab is more config surface than it buys.
 * The trade is no automatic resizing — which is why the upload path caps files
 * at 5 MB rather than relying on the renderer.
 */
export default function PostMedia({ src, alt, compact = false }: PostMediaProps) {
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-4 text-sm text-fg-subtle">
        <ImageOff className="w-3.5 h-3.5" />
        <span>The image could not be loaded.</span>
      </div>
    );
  }

  const capped = compact && !expanded;

  return (
    <figure className="relative overflow-hidden rounded-md border border-line bg-surface-2">
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={() => setFailed(true)}
        className={`w-full object-contain ${capped ? 'max-h-52' : 'max-h-[70vh]'}`}
      />

      {compact && !expanded && (
        <button
          type="button"
          onClick={(event) => {
            // The card as a whole navigates to the post; expanding is a
            // different intent and must not also follow the link.
            event.preventDefault();
            event.stopPropagation();
            setExpanded(true);
          }}
          className="absolute bottom-2 right-2 flex items-center gap-1.5 rounded-md border border-line bg-bg/80 px-2 py-1 text-xs text-fg-muted backdrop-blur-sm transition-colors hover:text-fg"
        >
          <Maximize2 className="w-3 h-3" />
          Expand
        </button>
      )}
    </figure>
  );
}
