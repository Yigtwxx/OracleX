'use client';

import type { OwnershipPosition } from '@/lib/api';
import { assetIdentityClass } from '@/lib/assetIdentity';
import SourceBadge from './SourceBadge';
import { UNKNOWN, formatPercent, formatQuantity, formatUsd } from './format';

interface PositionTableProps {
  positions: OwnershipPosition[];
  /** True when no prior observation exists, so deltas are absent by fact. */
  baseline: boolean;
  /**
   * The source already named in the header above this table.
   *
   * Rows matching it drop their badge: repeating "13F Q1 2026" down
   * twenty-nine identical lines is noise that buries the rows whose
   * provenance genuinely differs — the hand-entered cash figure sitting
   * beside them.
   */
  dominantSourceLabel?: string | null;
  onSelectAsset?: (symbol: string) => void;
}

const GRID = 'grid grid-cols-[minmax(0,1fr)_120px_110px_70px_90px] items-center gap-3 px-4 py-2.5';

/** Direction colour for a delta, and only for a delta. */
function deltaClass(value: number | null): string {
  if (value === null || value === 0) return 'text-fg-subtle';
  return value > 0 ? 'text-up' : 'text-down';
}

function deltaLabel(position: OwnershipPosition, baseline: boolean): string {
  if (baseline) return 'baseline';
  if (position.delta_pct === null) return '—';
  const sign = position.delta_pct > 0 ? '+' : '';
  return `${sign}${position.delta_pct.toFixed(1)}%`;
}

/**
 * One entity's holdings, largest first.
 *
 * The asset name carries its identity colour and nothing else — gold is gold
 * whether it rose or fell. Green and red live only in the delta column, which
 * is the sole place on this page where a colour means direction.
 *
 * An unpriced holding shows its quantity and says Unknown for the value. It is
 * never rendered as $0: the coin count is a fact, the dollar figure is missing,
 * and collapsing the two would turn a gap in our data into a claim about theirs.
 */
export default function PositionTable({
  positions,
  baseline,
  dominantSourceLabel,
  onSelectAsset,
}: PositionTableProps) {
  if (positions.length === 0) {
    return (
      <p className="px-4 py-6 text-center text-xs text-fg-subtle">
        No holdings could be sourced for this holder.
      </p>
    );
  }

  return (
    <div>
      <div
        className={`${GRID} border-b border-line text-2xs uppercase tracking-wide text-fg-subtle`}
      >
        <span>Holding</span>
        <span className="text-right">Quantity</span>
        <span className="text-right">Value</span>
        <span className="text-right">Weight</span>
        <span className="text-right">Change</span>
      </div>

      {positions.map((position) => {
        const symbol = position.symbol ?? position.label;
        const clickable = Boolean(onSelectAsset && position.symbol);

        return (
          <div
            key={position.key}
            className={`${GRID} border-b border-line last:border-b-0 hover:bg-surface-2`}
          >
            <div className="flex min-w-0 flex-col gap-1">
              <div className="flex min-w-0 items-center gap-2">
                {clickable ? (
                  <button
                    type="button"
                    onClick={() => onSelectAsset?.(position.symbol as string)}
                    className={`truncate text-left text-xs font-medium hover:underline ${assetIdentityClass(symbol)}`}
                    title={`Who else holds ${symbol}?`}
                  >
                    {position.label}
                  </button>
                ) : (
                  <span className={`truncate text-xs font-medium ${assetIdentityClass(symbol)}`}>
                    {position.label}
                  </span>
                )}
                {position.symbol && position.symbol !== position.label && (
                  <span className="shrink-0 text-2xs text-fg-subtle">{position.symbol}</span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {/* Manual rows always announce themselves; a person typed
                    those, and they must never blend into the filed ones. */}
                {(position.source.manual || position.source.label !== dominantSourceLabel) && (
                  <SourceBadge source={position.source} showDate />
                )}
                {position.note && <span className="text-2xs text-fg-subtle">{position.note}</span>}
              </div>
            </div>

            <span className="tabnum truncate text-right text-xs text-fg-muted">
              {formatQuantity(position.quantity, position.quantity_unit)}
            </span>

            <span
              className={`tabnum text-right text-xs ${position.value_usd === null ? 'text-fg-subtle' : 'text-fg'}`}
              title={
                position.value_basis === 'marked'
                  ? 'Derived: reported quantity × a price we fetched'
                  : position.value_basis === 'reported'
                    ? 'As published by the source'
                    : 'No published USD value'
              }
            >
              {formatUsd(position.value_usd)}
              {position.value_basis === 'marked' && (
                <span className="ml-1 text-2xs text-fg-subtle" aria-hidden>
                  ~
                </span>
              )}
            </span>

            <span className="tabnum text-right text-xs text-fg-muted">
              {position.weight_pct === null ? UNKNOWN : formatPercent(position.weight_pct)}
            </span>

            <span
              className={`tabnum text-right text-xs ${baseline ? 'text-fg-subtle' : deltaClass(position.delta_pct)}`}
            >
              {deltaLabel(position, baseline)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
