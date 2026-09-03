'use client';

import { ExternalLink } from 'lucide-react';

import type { BistOwnershipMove } from '@/lib/bist-api';
import { formatDateTime } from '@/lib/bist-format';

interface OwnershipMovesProps {
  moves: BistOwnershipMove[];
  /** What to say when the list is empty; the reason differs by page. */
  empty: string;
  limit?: number;
}

function bandClass(band: BistOwnershipMove['band']): string {
  if (band === 'high') return 'border-warn/60 text-warn';
  if (band === 'medium') return 'border-line-strong text-fg';
  return 'border-line text-fg-muted';
}

/**
 * The ownership-shaped filings — insider trades, block sales, tender offers,
 * capital actions — as one list.
 *
 * Every row links to the filing on KAP rather than restating it: the
 * classifier says what kind of filing it is, and the filing says what
 * happened. A headline that paraphrased the body would be the board's own
 * words standing in for the company's.
 */
export default function OwnershipMoves({ moves, empty, limit }: OwnershipMovesProps) {
  const rows = limit ? moves.slice(0, limit) : moves;

  if (rows.length === 0) {
    return <p className="px-3 py-4 text-sm text-fg-subtle">{empty}</p>;
  }

  return (
    <ul>
      {rows.map((move) => (
        <li key={move.id} className="border-b border-line last:border-0">
          <a
            href={move.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-start justify-between gap-3 px-3 py-2 transition-colors hover:bg-surface-2"
          >
            <span className="min-w-0">
              <span className="block truncate text-sm text-fg">{move.headline}</span>
              <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-2xs text-fg-subtle">
                <span className={`rounded border px-1 py-px ${bandClass(move.band)}`}>
                  {move.event_label}
                </span>
                <span>{formatDateTime(move.published_at)}</span>
              </span>
            </span>
            <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-fg-subtle" aria-hidden="true" />
          </a>
        </li>
      ))}
    </ul>
  );
}
