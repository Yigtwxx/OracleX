'use client';

import Link from 'next/link';
import { User } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

import type { CommunityAuthor } from '@/lib/api';

/**
 * The small pieces every post and comment repeats: flair tags, the plan badge,
 * and the author byline. Kept together so the feed and the detail page cannot
 * drift apart on them.
 */

export const TAG_CLASS = 'px-1.5 py-0.5 rounded text-2xs uppercase tracking-wide border';
export const NEUTRAL_TAG = `${TAG_CLASS} border-line text-fg-muted`;

export function PlanBadge({ plan }: { plan: string | null }) {
  if (plan !== 'whale' && plan !== 'pro') return null;
  return <span className={NEUTRAL_TAG}>{plan === 'whale' ? 'Whale' : 'Pro'}</span>;
}

export function Avatar({ author, size = 28 }: { author: CommunityAuthor; size?: number }) {
  return (
    <div
      className="rounded-full bg-surface-2 border border-line flex items-center justify-center overflow-hidden shrink-0"
      style={{ width: size, height: size }}
    >
      {author.avatar_url ? (
        // Plain <img>, matching the rest of the app: there is no next/image
        // anywhere here and no `images` config, and adding remotePatterns for
        // an avatar is more config than the byte savings are worth. The lint
        // warning is left visible rather than suppressed, so it reads the same
        // as the seven other <img> sites in this codebase.
        <img src={author.avatar_url} alt="" className="h-full w-full object-cover" />
      ) : (
        <User className="w-3.5 h-3.5 text-fg-subtle" />
      )}
    </div>
  );
}

export function relativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return formatDistanceToNow(date, { addSuffix: true });
}

interface BylineProps {
  author: CommunityAuthor;
  createdAt: string;
  isEdited?: boolean;
  /** Rendered before the author, e.g. a flair tag row. */
  prefix?: React.ReactNode;
  showAvatar?: boolean;
}

export function Byline({ author, createdAt, isEdited, prefix, showAvatar }: BylineProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap min-w-0 text-xs text-fg-subtle">
      {prefix}
      {showAvatar && <Avatar author={author} size={20} />}
      {/* `stopPropagation` because a PostCard in the feed is itself clickable:
          without it, clicking the name would open the post, not the person.
          `author.id` is nullable — a seeded or deleted author keeps plain text
          rather than linking to /u/null. */}
      {author.id ? (
        <Link
          href={`/u/${author.id}`}
          onClick={(event) => event.stopPropagation()}
          className="text-fg-muted truncate max-w-[14rem] transition-colors hover:text-fg hover:underline"
        >
          {author.full_name || 'Anonymous'}
        </Link>
      ) : (
        <span className="text-fg-muted truncate max-w-[14rem]">
          {author.full_name || 'Anonymous'}
        </span>
      )}
      <PlanBadge plan={author.subscription_plan} />
      <span aria-hidden="true">·</span>
      <time dateTime={createdAt}>{relativeTime(createdAt)}</time>
      {isEdited && (
        <>
          <span aria-hidden="true">·</span>
          <span title="This has been edited since it was posted">edited</span>
        </>
      )}
    </div>
  );
}
