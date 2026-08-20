'use client';

import type { OwnershipFlowNote } from '@/lib/api';
import Panel from '@/components/ui/Panel';
import AiNote from '@/components/ui/AiNote';
import { formatUsd } from '@/components/ownership/format';

interface FlowNoteProps {
  data: OwnershipFlowNote | undefined;
}

const TILT_LABEL: Record<string, string> = {
  net_buying: 'Net buying',
  net_selling: 'Net selling',
  balanced: 'Balanced',
  insufficient: 'Too few filings to call',
};

const TILT_TONE: Record<string, string> = {
  net_buying: 'text-up',
  net_selling: 'text-down',
  balanced: 'text-fg-muted',
  insufficient: 'text-fg-subtle',
};

/**
 * What the tracked institutions did last quarter, in prose.
 *
 * The panels below this one rank moves by size. None of them can show the two
 * things this says: whether the quarter leaned one way overall, which needs the
 * whole set to compute, and where holders took opposite sides of the same name,
 * which is invisible in any list sorted by size.
 *
 * The header row is deterministic and renders without the sentence. Where the
 * totals are floors — some filings carry no dollar value — they are labelled
 * floors rather than quietly counted as zero, which is the same rule the rest of
 * this feature follows in refusing to render `UNKNOWN` as a 0.
 */
export default function FlowNote({ data }: FlowNoteProps) {
  const facts = data?.facts;

  // No board yet, or every tracked holder is on its first filing. Both mean
  // there is no quarter-over-quarter change to narrate, which is not the same
  // as a quarter in which nobody traded — so the panel is absent rather than
  // empty.
  if (!facts) return null;

  const filed =
    facts.filed_from && facts.filed_to
      ? `filed ${facts.filed_from} to ${facts.filed_to}`
      : 'filing dates not recorded';

  return (
    <Panel
      title="Institutional flow"
      footnote={`${facts.quarter} — positions held on ${facts.period}, ${filed}. Values as filed.`}
    >
      <div className="p-4 flex flex-col gap-2.5">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5">
          <span className={`text-md font-semibold ${TILT_TONE[facts.tilt]}`}>
            {TILT_LABEL[facts.tilt]}
          </span>

          <span className="text-xs text-fg-subtle font-mono tabnum">
            {formatUsd(facts.gross_bought_usd)} added / {formatUsd(facts.gross_sold_usd)} trimmed
            {facts.value_is_partial && ' (floors)'}
          </span>

          <span className="text-xs text-fg-subtle">
            {facts.entities_reporting} of {facts.entities_tracked} holders reporting
          </span>
        </div>

        <AiNote aiNote={data?.note} />
      </div>
    </Panel>
  );
}
