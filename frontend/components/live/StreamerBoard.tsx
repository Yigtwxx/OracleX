'use client';

import { useMemo, useState } from 'react';
import { AlertTriangle, ExternalLink } from 'lucide-react';
import type { LiveStreamer } from '@/lib/api';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';

type RegionFilter = 'all' | 'tr' | 'global';
type PlatformFilter = 'all' | 'youtube' | 'kick';

const REGION_FILTERS: { value: RegionFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'tr', label: 'Türkiye' },
  { value: 'global', label: 'Global' },
];

/**
 * The platform filter earns its place rather than being symmetry with region.
 *
 * The list sorts live first, and Kick's finance side is small enough that its
 * channels are usually all off air — which buries them under twenty YouTube
 * rows, where "which platform is this on" stops being answerable by scrolling.
 * One chip brings them back.
 */
const PLATFORM_FILTERS: { value: PlatformFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'kick', label: 'Kick' },
];

/** Each platform's own signal colour — YouTube red, Kick green — as a bordered chip. */
const PLATFORM_CLASS: Record<string, string> = {
  youtube: 'bg-down-bg text-down border-down/40',
  kick: 'bg-up-bg text-up border-up/40',
};

const PLATFORM_LABEL: Record<string, string> = {
  youtube: 'YouTube',
  kick: 'Kick',
};

interface StreamerBoardProps {
  streamers: LiveStreamer[];
  liveCount: number;
  isLoading: boolean;
}

/**
 * Who covering markets is broadcasting right now.
 *
 * Status only — every row links out. Nothing is embedded here: these are
 * commentary streams, and the one video frame this page has belongs to the
 * event that is actually moving the market.
 */
export default function StreamerBoard({ streamers, liveCount, isLoading }: StreamerBoardProps) {
  const [region, setRegion] = useState<RegionFilter>('all');
  const [platform, setPlatform] = useState<PlatformFilter>('all');

  const rows = useMemo(
    () =>
      streamers.filter(
        (s) =>
          (region === 'all' || s.region === region) &&
          (platform === 'all' || s.platform === platform)
      ),
    [streamers, region, platform]
  );

  if (isLoading) return <PanelSkeleton />;

  const unreachable = rows.filter((row) => row.probe_failed).length;

  return (
    <Panel
      title="Streamers"
      action={
        <div className="flex items-center gap-2">
          <span className="text-xs text-fg-subtle">{liveCount} live</span>
          <div role="group" aria-label="Filter streamers by region" className="flex gap-1">
            {REGION_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                aria-pressed={region === value}
                onClick={() => setRegion(value)}
                className={`px-2 py-0.5 rounded-md text-xs transition-colors ${
                  region === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <span aria-hidden className="w-px h-3.5 bg-line" />
          <div role="group" aria-label="Filter streamers by platform" className="flex gap-1">
            {PLATFORM_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                aria-pressed={platform === value}
                onClick={() => setPlatform(value)}
                className={`px-2 py-0.5 rounded-md text-xs transition-colors ${
                  platform === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      }
      footnote={
        unreachable > 0
          ? `${unreachable} channel${unreachable === 1 ? '' : 's'} could not be checked — shown as unknown, not offline`
          : 'Live status is checked when this tab is open, and cached for ten minutes'
      }
    >
      {rows.length === 0 ? (
        <div className="px-4 py-10 text-center">
          <p className="text-base text-fg-muted">No streamers match this filter.</p>
        </div>
      ) : (
        <div className="divide-y divide-line">
          {rows.map((streamer) => (
            <a
              key={streamer.key}
              href={streamer.url ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2.5 flex items-center gap-3 hover:bg-surface-2 transition-colors"
            >
              {/* Status column. A failed probe gets its own mark rather than
                  falling in with the offline rows — "we could not check" and
                  "they are not streaming" are different things to tell someone. */}
              <span className="w-12 shrink-0">
                {streamer.probe_failed ? (
                  <AlertTriangle className="w-3.5 h-3.5 text-warn" aria-label="Could not check" />
                ) : streamer.is_live ? (
                  <span className="flex items-center gap-1 px-1.5 py-px rounded bg-down-bg text-down text-2xs uppercase tracking-wide">
                    <span className="w-1 h-1 rounded-full bg-down live-indicator" />
                    Live
                  </span>
                ) : (
                  <span className="text-2xs text-fg-subtle">Offline</span>
                )}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-base text-fg">{streamer.name}</span>
                  {/* Which platform this is on carries a border as well as a
                      hue: at 10px the fill alone reads as a tint on the text
                      rather than as a chip, and it is the one field on the row
                      that has no other way to be inferred. */}
                  <span
                    className={`px-1.5 py-px rounded border text-2xs font-medium tracking-wide ${
                      PLATFORM_CLASS[streamer.platform] ?? 'bg-surface-2 text-fg-subtle border-line'
                    }`}
                  >
                    {PLATFORM_LABEL[streamer.platform] ?? streamer.platform}
                  </span>
                  {streamer.focus && (
                    <span className="text-2xs text-fg-subtle">{streamer.focus}</span>
                  )}
                </div>
                {streamer.title && (
                  <div className="text-xs text-fg-muted truncate">{streamer.title}</div>
                )}
              </div>

              <div className="shrink-0 flex items-center gap-2 text-xs text-fg-subtle">
                {streamer.viewers !== null && (
                  <span className="font-mono tabnum">
                    {streamer.viewers.toLocaleString('en-US')}
                  </span>
                )}
                <ExternalLink className="w-3 h-3" />
              </div>
            </a>
          ))}
        </div>
      )}
    </Panel>
  );
}
