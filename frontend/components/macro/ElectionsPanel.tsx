'use client';

import { useState } from 'react';
import { AlertCircle, ExternalLink } from 'lucide-react';
import Panel, { PanelSkeleton } from '@/components/ui/Panel';
import {
  Election,
  ElectionsBoard,
  TierFilter,
  applyTierFilter,
  daysUntil,
  formatCountdown,
  formatMomentum,
  formatPrice,
  formatWhen,
  groupByMonth,
  horizonNote,
  leadOutcome,
  oddsState,
  urgencyTier,
} from '@/lib/elections';

interface ElectionsPanelProps {
  data: ElectionsBoard | undefined;
  isLoading: boolean;
  isError: boolean;
}

const FILTERS: { value: TierFilter; label: string }[] = [
  { value: 'tracked', label: 'Tracked' },
  { value: 'all', label: 'All' },
];

export default function ElectionsPanel({ data, isLoading, isError }: ElectionsPanelProps) {
  const [filter, setFilter] = useState<TierFilter>('tracked');
  if (isLoading) return <PanelSkeleton />;

  const all = data?.elections ?? [];
  const rows = applyTierFilter(all, filter);
  const groups = groupByMonth(rows);
  const now = Date.now();

  return (
    <Panel
      title="Elections"
      action={
        <div className="flex items-center gap-3">
          {/* An odds outage and a world with no election markets would otherwise
              be byte-identical on this panel: every row blank, no explanation.
              The badge is the difference. */}
          {data && !data.odds_available && (
            <span
              title="Prediction-market feed unavailable — dates are unaffected"
              className="px-1.5 py-0.5 rounded border border-line text-2xs uppercase tracking-wide text-fg-subtle"
            >
              No odds
            </span>
          )}
          <div role="group" aria-label="Filter elections" className="flex items-center gap-1">
            {FILTERS.map(({ value, label }) => (
              <button
                key={value}
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={`px-2 py-0.5 rounded-md text-xs transition-colors ${
                  filter === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      }
      columns={
        rows.length > 0 ? (
          <div className="flex items-center gap-3 h-7 px-4 bg-surface-2">
            <span className="label w-16 shrink-0">Date</span>
            <span className="label w-12 shrink-0 text-right">In</span>
            <span className="label flex-1 min-w-0">Country / office</span>
            <span className="label w-56 shrink-0">Market</span>
            <span className="label w-36 shrink-0 text-right">Watch</span>
          </div>
        ) : undefined
      }
      footnote={data ? horizonNote(all, data.odds_cap, data.odds_available) : undefined}
    >
      {/* A failed feed is not a quiet year — the two must not look the same. */}
      {isError ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          <span className="text-base">Electoral calendar unavailable</span>
        </div>
      ) : all.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 text-fg-subtle gap-2">
          <AlertCircle className="w-5 h-5" />
          <span className="text-base">No national elections scheduled ahead</span>
        </div>
      ) : rows.length === 0 ? (
        /* Filtered to nothing keeps its filter strip above it, so the way back
           is visible from the empty state itself. */
        <div className="px-4 py-10 text-center">
          <p className="text-base text-fg-muted">No tracked countries vote in this window.</p>
          <p className="mt-1 text-xs text-fg-subtle">
            {all.length} scheduled elsewhere — switch to All to see them.
          </p>
        </div>
      ) : (
        <div>
          {/* Rows of cells rather than a table: a sticky `th` is scoped to the
              whole table, so month headings would stack at the top instead of
              being pushed out by their own group. A block per month is its own
              containing block. z-[1] keeps them under the card's lit rim at 3. */}
          {groups.map((group) => (
            <section key={group.label}>
              {/* Margin, not padding: an opaque sticky bar that reaches the
                  right edge paints over macOS's overlay scrollbar thumb. */}
              <h4 className="label sticky top-0 z-[1] mr-[var(--scrollbar-w)] px-4 py-1 bg-surface border-t border-line text-fg-muted">
                {group.label}
              </h4>
              {group.rows.map((row) => (
                <ElectionRow key={row.id} row={row} now={now} />
              ))}
            </section>
          ))}
        </div>
      )}
    </Panel>
  );
}

function ElectionRow({ row, now }: { row: Election; now: number }) {
  const days = row.precision === 'month' ? undefined : daysUntil(row.date, now);
  const urgency = urgencyTier(days);

  return (
    <div className="flex items-baseline gap-3 px-4 py-2 border-t border-line hover:bg-surface-2 transition-colors">
      <span className="w-16 shrink-0 text-xs font-mono tabnum text-fg-subtle">
        {formatWhen(row)}
      </span>
      {/* Class pairs are literal strings, never assembled from a variable:
          Tailwind scans source text and would not see a computed name. */}
      <span
        className={`w-12 shrink-0 text-right text-xs font-mono tabnum ${
          urgency === 'imminent' ? 'text-warn' : 'text-fg-subtle'
        }`}
      >
        {formatCountdown(days)}
      </span>

      <span className="flex-1 min-w-0 flex items-baseline gap-2">
        {/* Larger than the row's text: an emoji flag draws well inside its em
            box, so at the body size it reads as a smudge rather than a country. */}
        <span className="shrink-0 text-lg leading-none" aria-hidden="true">
          {row.flag}
        </span>
        <span className="min-w-0">
          <span className={`text-base ${row.tier ? 'text-fg' : 'text-fg-muted'}`}>
            {row.country}
          </span>
          <span className="ml-2 text-xs text-fg-subtle">{row.office}</span>
        </span>
      </span>

      <span className="w-56 shrink-0 min-w-0">
        <MarketCell row={row} />
      </span>

      <span className="w-36 shrink-0 text-right text-xs font-mono tabnum text-fg-subtle truncate">
        {row.tickers.length > 0 ? row.tickers.join(' · ') : '–'}
      </span>
    </div>
  );
}

/**
 * The market column, in the three states it is allowed to have.
 *
 * The date on this row is a cited fact and the market beside it is a heuristic
 * match, so the price is rendered subordinate to the country and carries what
 * it matched on. One bad join at equal weight teaches a reader to distrust the
 * dates too.
 */
function MarketCell({ row }: { row: Election }) {
  const state = oddsState(row);

  if (state === 'unmatched') {
    return <span className="text-xs text-fg-subtle">–</span>;
  }

  if (state === 'linked') {
    const link = row.market_link!;
    return (
      <a
        href={link.url}
        target="_blank"
        rel="noopener noreferrer"
        title={`Related market — matched on ${link.matched_on.join(', ')}. Not priced: the match is not confident enough to quote.`}
        className="inline-flex items-center gap-1 text-xs text-fg-subtle hover:text-fg-muted transition-colors"
      >
        Related market
        <ExternalLink className="w-3 h-3" />
      </a>
    );
  }

  const odds = row.odds!;
  const lead = leadOutcome(odds);
  if (!lead) return <span className="text-xs text-fg-subtle">–</span>;
  const momentum = formatMomentum(lead.change_1w);

  return (
    <a
      href={odds.url}
      target="_blank"
      rel="noopener noreferrer"
      title={`${odds.event_title} — matched on ${odds.matched_on.join(', ')}`}
      className="group flex items-baseline gap-2 min-w-0"
    >
      <span className="text-xs font-mono tabnum text-fg">{formatPrice(lead.price)}</span>
      <span className="min-w-0 truncate text-xs text-fg-muted group-hover:text-fg transition-colors">
        {lead.label}
      </span>
      {momentum !== undefined && (
        <span
          className={`shrink-0 text-2xs font-mono tabnum ${
            momentum.startsWith('+')
              ? 'text-up'
              : momentum.startsWith('−')
                ? 'text-down'
                : 'text-fg-subtle'
          }`}
        >
          {momentum}
        </span>
      )}
    </a>
  );
}
