'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { useAssetBrief } from '@/hooks/queries';
import {
  DEFAULT_BRIEF_SYMBOLS,
  MAX_BRIEF_SYMBOLS,
  addSymbol,
  readBriefSymbols,
  setSlot,
  writeBriefSymbols,
} from '@/lib/asset-brief';
import AssetBriefCard from './AssetBriefCard';
import AssetPicker from './AssetPicker';

/**
 * The assets the reader actually follows, at the top of Home.
 *
 * Three fixed slots rather than a list. The block replaced eight market-wide
 * on-chain cards, and the reason those left was that the top of this page was
 * costing a screen to say things nobody had asked about — a slot count that
 * grows would put the page straight back where it was.
 *
 * Width is carried by `flex-grow` and not by grid spans, because the expand has
 * to animate: `grid-column: span 3` has no interpolable in-between, so a grid
 * version snaps between layouts. Three cards at `grow-1` are equal thirds; one
 * at `grow-3` beside two at `grow-1` is 60/20/20, and CSS animates the number.
 */
export default function AssetBrief() {
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_BRIEF_SYMBOLS);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);

  // Read after mount, not during render. `localStorage` does not exist on the
  // server, and seeding state from it directly would make the first client
  // render disagree with the HTML Next.js sent.
  useEffect(() => {
    setSymbols(readBriefSymbols());
  }, []);

  const commit = useCallback((next: string[]) => {
    setSymbols(next);
    writeBriefSymbols(next);
  }, []);

  const isPickingNew = editing === symbols.length;

  return (
    <section aria-label="Your asset brief">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="label">My Brief</h2>
        {symbols.length < MAX_BRIEF_SYMBOLS && (
          <button
            onClick={() => setEditing(symbols.length)}
            className="flex items-center gap-1 text-2xs text-fg-subtle transition-colors hover:text-fg"
          >
            <Plus className="h-3 w-3" />
            Add asset
          </button>
        )}
      </div>

      <div className="flex flex-col gap-3 lg:h-[340px] lg:flex-row">
        {symbols.map((symbol, index) => (
          <Slot
            key={symbol}
            symbol={symbol}
            isExpanded={expanded === symbol}
            isCollapsed={expanded !== null && expanded !== symbol}
            onToggle={() => setExpanded((current) => (current === symbol ? null : symbol))}
            onEdit={() => setEditing(index)}
          />
        ))}

        {symbols.length === 0 && (
          <button
            onClick={() => setEditing(0)}
            className="surface flex h-[200px] w-full flex-col items-center justify-center gap-1.5 text-fg-subtle transition-colors hover:text-fg"
          >
            <Plus className="h-4 w-4" />
            <span className="text-xs">Pick an asset to follow</span>
          </button>
        )}
      </div>

      <AssetPicker
        isOpen={editing !== null}
        current={editing !== null ? (symbols[editing] ?? null) : null}
        taken={symbols}
        onClose={() => setEditing(null)}
        onPick={(symbol) => {
          if (editing === null) return;
          commit(isPickingNew ? addSymbol(symbols, symbol) : setSlot(symbols, editing, symbol));
        }}
        onRemove={
          isPickingNew || editing === null
            ? undefined
            : () => {
                const removed = symbols[editing];
                if (expanded === removed) setExpanded(null);
                commit(setSlot(symbols, editing, null));
              }
        }
      />
    </section>
  );
}

/**
 * One slot, and its own query.
 *
 * The hook lives here rather than in the parent so React Query keys the cache
 * per symbol: swapping one slot refetches that symbol alone, and a ticker the
 * backend cannot resolve fails inside its own card instead of emptying the row.
 */
function Slot({
  symbol,
  isExpanded,
  isCollapsed,
  onToggle,
  onEdit,
}: {
  symbol: string;
  isExpanded: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
  onEdit: () => void;
}) {
  const { data, isLoading, error } = useAssetBrief(symbol);

  return (
    <div
      className={`min-w-0 grow basis-0 transition-[flex-grow] duration-300 ease-out ${
        isExpanded ? 'lg:grow-[3]' : ''
      }`}
    >
      <AssetBriefCard
        symbol={symbol}
        brief={data}
        isLoading={isLoading}
        error={error}
        isExpanded={isExpanded}
        isCollapsed={isCollapsed}
        onToggle={onToggle}
        onEdit={onEdit}
      />
    </div>
  );
}
