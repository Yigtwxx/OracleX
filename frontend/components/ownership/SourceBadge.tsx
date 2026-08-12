'use client';

import { ExternalLink } from 'lucide-react';
import type { OwnershipSourceRef } from '@/lib/api';
import { formatDate } from './format';

interface SourceBadgeProps {
  source: OwnershipSourceRef;
  /** Adds the date the figure describes, when the source publishes one. */
  showDate?: boolean;
  /**
   * Render as plain text even when the source has a URL.
   *
   * Required inside the grid cards, which are themselves links: an anchor
   * nested in an anchor is invalid HTML and React refuses to hydrate it. The
   * card's own destination already leads to the detail view, where the badge
   * is clickable.
   */
  asText?: boolean;
  className?: string;
}

/**
 * Where a number came from, said plainly beside it.
 *
 * A hand-maintained row takes the warn token. That is a status, not decoration:
 * this figure did not come from an API, a person copied it out of a filing, and
 * it must not sit on the page looking like the rows that did.
 *
 * The date shown is `as_of` — the period the figure describes — and never
 * `retrieved_at`. A Q3 filing pulled this morning is fresh data about a stale
 * quarter, and labelling it with today would be the single most misleading
 * thing this page could do. Sources that publish no as-of date say "retrieved"
 * instead of borrowing one.
 */
export default function SourceBadge({
  source,
  showDate = false,
  asText = false,
  className = '',
}: SourceBadgeProps) {
  const asOf = formatDate(source.as_of);
  const retrieved = formatDate(source.retrieved_at);

  const tone = source.manual
    ? 'border-warn text-warn'
    : 'border-line text-fg-subtle hover:text-fg-muted';

  const dateSuffix = showDate
    ? asOf
      ? ` · ${asOf}`
      : retrieved
        ? ` · ret. ${retrieved}`
        : ''
    : '';

  const label = `${source.manual ? 'MANUAL · ' : ''}${source.label}${dateSuffix}`;

  const title = [
    source.label,
    asOf ? `As of ${asOf}` : 'This source publishes no as-of date',
    retrieved ? `Retrieved ${retrieved}` : null,
    source.manual ? 'Entered by hand from a published report' : null,
  ]
    .filter(Boolean)
    .join(' — ');

  const shell = `inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-2xs uppercase tracking-wide whitespace-nowrap transition-colors ${tone} ${className}`;

  if (source.url && !asText) {
    return (
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className={shell}
        title={title}
      >
        {label}
        <ExternalLink className="h-2.5 w-2.5" aria-hidden />
      </a>
    );
  }

  return (
    <span className={shell} title={title}>
      {label}
    </span>
  );
}
