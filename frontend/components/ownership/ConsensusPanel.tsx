'use client';

import type { OwnershipConsensusRow } from '@/lib/api';
import { useOwnershipConsensus } from '@/hooks/queries';
import Panel from '@/components/ui/Panel';
import { assetIdentityClass } from '@/lib/assetIdentity';
import { formatUsd } from './format';

interface ConsensusPanelProps {
  onSelectAsset?: (symbol: string) => void;
}

interface ListProps {
  rows: OwnershipConsensusRow[];
  entityCount: number;
  /** Ranked by holders, so the count needs a word beside it. */
  countLabel: string;
  onSelectAsset?: (symbol: string) => void;
  empty: string;
}

function ConsensusList({ rows, entityCount, countLabel, onSelectAsset, empty }: ListProps) {
  if (rows.length === 0) {
    return <p className="px-4 py-5 text-center text-xs text-fg-subtle">{empty}</p>;
  }

  return (
    <ul>
      {rows.map((row) => {
        const symbol = row.symbol ?? row.label;
        const holders = row.holder_names ?? row.holders ?? [];
        return (
          <li
            key={`${symbol}-${row.label}`}
            className="flex items-center gap-3 border-b border-line px-4 py-2 last:border-b-0 hover:bg-surface-2"
          >
            {/* Proportion of the tracked set, not of the market. The
                denominator is stated so the bar cannot be read as market share. */}
            <span
              className="tabnum w-12 shrink-0 text-xs text-fg-muted"
              title={`${row.holder_count} of ${entityCount} tracked holders`}
            >
              {row.holder_count}/{entityCount}
            </span>

            {/* The ticker rides along because share classes share a name:
                Alphabet appears as both GOOG and GOOGL, and two rows reading
                "Alphabet Inc" look like a duplicate rather than the two
                different securities they are. */}
            <span className="flex min-w-0 flex-1 items-baseline gap-1.5">
              {onSelectAsset && row.symbol ? (
                <button
                  type="button"
                  onClick={() => onSelectAsset(row.symbol as string)}
                  className={`truncate text-left text-xs font-medium hover:underline ${assetIdentityClass(symbol)}`}
                >
                  {row.label}
                </button>
              ) : (
                <span className={`truncate text-xs font-medium ${assetIdentityClass(symbol)}`}>
                  {row.label}
                </span>
              )}
              {row.symbol && row.symbol !== row.label && (
                <span className="shrink-0 text-2xs text-fg-subtle">{row.symbol}</span>
              )}
            </span>

            <span
              className="tabnum shrink-0 text-xs text-fg-muted"
              title={
                row.value_is_partial
                  ? 'Partial — some holders publish no USD value for this'
                  : `Combined across ${countLabel}`
              }
            >
              {formatUsd(row.total_value_usd)}
              {row.value_is_partial && <span className="ml-0.5 text-fg-subtle">+</span>}
            </span>

            <span
              className="hidden w-40 shrink-0 truncate text-2xs text-fg-subtle lg:block"
              title={holders.join(', ')}
            >
              {holders.slice(0, 2).join(', ')}
              {holders.length > 2 && ` +${holders.length - 2}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The board read across holders rather than one at a time.
 *
 * Ranked by how many holders report a thing, not by how many dollars are in it.
 * A single $57bn Apple position is a fact about Berkshire; six separate holders
 * owning bitcoin is a fact about the market, and only the second one is what
 * the word consensus means.
 */
export default function ConsensusPanel({ onSelectAsset }: ConsensusPanelProps) {
  const consensus = useOwnershipConsensus();

  if (consensus.isError) return null;

  const data = consensus.data;
  const entityCount = data?.entity_count ?? 0;
  // Withheld until the count is real. "Across 0 tracked holders" printed while
  // the request is still in flight is a false statement about the data, not a
  // loading indicator.
  const scopeNote = data ? `Across ${entityCount} tracked holders` : undefined;

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
      <Panel title="Most held" footnote={scopeNote} className="min-h-[13rem]">
        {consensus.isLoading ? (
          <div className="shimmer h-40" />
        ) : (
          <ConsensusList
            rows={data?.most_held ?? []}
            entityCount={entityCount}
            countLabel="every holder reporting it"
            onSelectAsset={onSelectAsset}
            empty="Nothing held in common yet."
          />
        )}
      </Panel>

      <Panel
        title="Most bought"
        footnote={data ? 'From the moves on record' : undefined}
        className="min-h-[13rem]"
      >
        {consensus.isLoading ? (
          <div className="shimmer h-40" />
        ) : (
          <ConsensusList
            rows={data?.most_bought ?? []}
            entityCount={entityCount}
            countLabel="every buyer"
            onSelectAsset={onSelectAsset}
            empty="No purchases on record yet."
          />
        )}
      </Panel>

      <Panel
        title="Most sold"
        footnote={data ? 'From the moves on record' : undefined}
        className="min-h-[13rem]"
      >
        {consensus.isLoading ? (
          <div className="shimmer h-40" />
        ) : (
          <ConsensusList
            rows={data?.most_sold ?? []}
            entityCount={entityCount}
            countLabel="every seller"
            onSelectAsset={onSelectAsset}
            empty="No sales on record yet."
          />
        )}
      </Panel>
    </div>
  );
}
