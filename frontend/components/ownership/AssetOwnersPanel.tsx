'use client';

import { useAssetOwners } from '@/hooks/queries';
import Modal from '@/components/ui/Modal';
import SourceBadge from './SourceBadge';
import { UNKNOWN, formatPercent, formatQuantity, formatUsd } from './format';

interface AssetOwnersPanelProps {
  symbol: string | null;
  onClose: () => void;
  onSelectEntity: (entityId: string) => void;
}

/**
 * The board turned inside out: one asset, everyone we track who holds it.
 *
 * Free from data already on the page, and the question people actually arrive
 * with — "who owns bitcoin" gets asked far more often than "what does SharpLink
 * own". Opens over the current view rather than navigating, so the holder being
 * read is still there when it closes.
 */
export default function AssetOwnersPanel({
  symbol,
  onClose,
  onSelectEntity,
}: AssetOwnersPanelProps) {
  const owners = useAssetOwners(symbol);

  if (!symbol) return null;

  const rows = owners.data?.owners ?? [];

  return (
    <Modal isOpen onClose={onClose} title={`Who holds ${symbol}`} maxWidth="max-w-2xl">
      <p className="mb-2 text-2xs text-fg-subtle">
        Among the holders tracked on this page — not the whole market.
      </p>

      {owners.isLoading ? (
        <div className="shimmer h-32 rounded" />
      ) : rows.length === 0 ? (
        <p className="py-6 text-center text-xs text-fg-subtle">
          None of the tracked holders report {symbol}.
        </p>
      ) : (
        <ul className="max-h-[55vh] overflow-y-auto custom-scrollbar">
          {rows.map((owner) => (
            <li key={`${owner.entity_id}-${owner.label}`}>
              <button
                type="button"
                onClick={() => onSelectEntity(owner.entity_id)}
                className="flex w-full items-center gap-3 border-b border-line px-1 py-2.5 text-left last:border-b-0 hover:bg-surface-2"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium text-fg">
                    {owner.entity_name}
                  </span>
                  <SourceBadge source={owner.source} showDate asText className="mt-1" />
                </span>

                <span className="tabnum shrink-0 text-right text-xs text-fg-muted">
                  {formatQuantity(owner.quantity, owner.quantity_unit)}
                </span>

                <span
                  className={`tabnum w-20 shrink-0 text-right text-xs ${owner.value_usd === null ? 'text-fg-subtle' : 'text-fg'}`}
                >
                  {formatUsd(owner.value_usd)}
                </span>

                <span className="tabnum w-14 shrink-0 text-right text-2xs text-fg-subtle">
                  {owner.weight_pct === null ? UNKNOWN : formatPercent(owner.weight_pct)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
