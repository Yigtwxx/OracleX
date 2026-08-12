'use client';

import { useMemo } from 'react';
import { VideoOff } from 'lucide-react';
import type { LiveEvent, LiveStreamChannel } from '@/lib/api';

interface StreamPlayerProps {
  channels: LiveStreamChannel[];
  /** The row the user clicked, if any — its own broadcast wins over the channel list. */
  selectedEvent: LiveEvent | null;
  /** Which channel the user pinned, or null to let the resolution below choose. */
  pinnedKey: string | null;
  isLoading: boolean;
}

/** YouTube embed parameters. Muted because browsers refuse unmuted autoplay anyway,
 *  and an unprompted voice in a terminal UI is hostile even when it is allowed. */
const EMBED_PARAMS = 'autoplay=0&mute=1&rel=0&modestbranding=1';

function withParams(url: string): string {
  return `${url}${url.includes('?') ? '&' : '?'}${EMBED_PARAMS}`;
}

/**
 * Resolves what should be playing, in priority order.
 *
 * Exported so the hero can label the frame with the same answer the player
 * arrived at, without either of them re-deriving it.
 */
export function resolveSource(
  channels: LiveStreamChannel[],
  selectedEvent: LiveEvent | null,
  pinnedKey: string | null
): { source: string | null; caption: string | null; watchUrl: string | null } {
  const pinned = pinnedKey ? channels.find((channel) => channel.key === pinnedKey) : undefined;
  if (pinned) {
    return {
      source: pinned.embed_url,
      caption: pinned.is_live ? (pinned.title ?? `${pinned.name} is live`) : pinned.name,
      watchUrl: pinned.watch_url,
    };
  }

  if (selectedEvent?.embed_url) {
    return {
      source: selectedEvent.embed_url,
      caption: selectedEvent.title,
      watchUrl: selectedEvent.watch_url,
    };
  }

  // A channel that is live *because* something is happening beats one that is
  // always live — the White House going on air is the news; CNBC being on air
  // at 3am is not.
  const newsworthy = channels.find((channel) => channel.is_live && channel.implies !== 'market');
  const rolling = channels.find((channel) => channel.is_live);
  const chosen = newsworthy ?? rolling ?? channels[0];
  if (!chosen) return { source: null, caption: null, watchUrl: null };

  return {
    source: chosen.embed_url,
    caption: chosen.is_live ? (chosen.title ?? `${chosen.name} is live`) : chosen.name,
    watchUrl: chosen.watch_url,
  };
}

/** The 16:9 frame itself. Chrome around it belongs to whoever renders it. */
export default function StreamPlayer({
  channels,
  selectedEvent,
  pinnedKey,
  isLoading,
}: StreamPlayerProps) {
  const { source, caption } = useMemo(
    () => resolveSource(channels, selectedEvent, pinnedKey),
    [channels, selectedEvent, pinnedKey]
  );

  if (isLoading) {
    return <div className="aspect-video w-full rounded-md border border-line shimmer" />;
  }

  if (!source) {
    return (
      <div className="aspect-video w-full rounded-md border border-line flex flex-col items-center justify-center gap-2 text-center">
        <VideoOff className="w-5 h-5 text-fg-subtle" />
        <p className="text-sm text-fg-muted">No broadcast channel is reachable.</p>
      </div>
    );
  }

  return (
    <div className="aspect-video w-full overflow-hidden rounded-md border border-line bg-bg">
      {/* Keyed on the source alone. Anything else here — a poll counter, a
          timestamp — would remount the iframe and restart the stream from the
          top every time the page refetched. */}
      <iframe
        key={source}
        src={withParams(source)}
        title={caption ?? 'Live broadcast'}
        allow="accelerometer; autoplay; encrypted-media; picture-in-picture"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
        className="w-full h-full border-0"
      />
    </div>
  );
}
