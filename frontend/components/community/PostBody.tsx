'use client';

import Markdown from '@/components/ui/Markdown';
import type { CommunityPost } from '@/lib/api';

import LinkPreviewCard from './LinkPreviewCard';
import PostMedia from './PostMedia';

interface PostBodyProps {
  post: CommunityPost;
  /** Feed mode: the media is capped so text and chart both survive the clip. */
  compact?: boolean;
}

/**
 * Renders a post's payload according to its kind.
 *
 * Nothing is truncated by character count — that cuts markdown mid-syntax and
 * turns a half-shown table into a wall of pipes. In the feed the *card* clips
 * this whole body to a fixed height and fades the cut edge (see PostCard), so
 * the only thing compact mode does here is keep an image from eating the entire
 * visible area before the prose gets a chance to show.
 */
export default function PostBody({ post, compact = false }: PostBodyProps) {
  const prose = post.content.trim() ? (
    <Markdown content={post.content} variant="community" className="max-w-none" />
  ) : null;

  if (post.post_kind === 'image' && post.image_url) {
    const media = (
      <PostMedia
        src={post.image_url}
        alt={post.title || 'Image shared with this post'}
        compact={compact}
      />
    );

    // The card clips its body, so in the feed the chart goes above the prose —
    // otherwise a long write-up pushes the very thing the post is about past the
    // fade. On the detail page nothing is clipped and the author's order stands.
    return (
      <div className="space-y-2.5">
        {compact ? (
          <>
            {media}
            {prose}
          </>
        ) : (
          <>
            {prose}
            {media}
          </>
        )}
      </div>
    );
  }

  if (post.post_kind === 'link' && post.link) {
    return (
      <div className="space-y-2.5">
        {prose}
        <LinkPreviewCard link={post.link} />
      </div>
    );
  }

  return prose;
}
