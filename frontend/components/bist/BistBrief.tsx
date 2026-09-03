'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus } from 'lucide-react';

import {
  DEFAULT_BIST_BRIEF,
  MAX_BIST_BRIEF,
  addBistSlot,
  readBistBrief,
  setBistSlot,
  slotKey,
  writeBistBrief,
  type BistBriefSlot,
} from '@/lib/bist-brief';
import BistBriefCard from './BistBriefCard';
import BistBriefPicker from './BistBriefPicker';

/**
 * The instruments the reader actually follows, at the top of the BIST board.
 *
 * This replaced a strip of eight index tiles. Seven of those eight were the
 * same number in different slices — a reader who knows what XU050 is does not
 * learn anything from it sitting beside XU100 — and they cost the first screen
 * of the realm's landing page to say something nobody had asked. XU100 and
 * XU030 kept their place in the market rail on the right, where the rest of
 * the day's context already is.
 *
 * Three fixed slots rather than a list, for the same reason the crypto board
 * has three: a count that grows would put the page straight back where it was.
 *
 * Width is carried by `flex-grow` and not by grid spans, because the expand has
 * to animate: `grid-column: span 3` has no interpolable in-between, so a grid
 * version snaps between layouts.
 *
 * The band is a fixed height so the board below it does not jump when a card
 * expands, and it is tall enough to reach the model's sentence: a card whose
 * note sits permanently below its own fold has a note nobody reads. What does
 * not fit scrolls inside the card.
 */
export default function BistBrief() {
  const [slots, setSlots] = useState<BistBriefSlot[]>([...DEFAULT_BIST_BRIEF]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<number | null>(null);

  // Read after mount, not during render. `localStorage` does not exist on the
  // server, and seeding state from it directly would make the first client
  // render disagree with the HTML Next.js sent.
  useEffect(() => {
    setSlots(readBistBrief());
  }, []);

  const commit = useCallback((next: BistBriefSlot[]) => {
    setSlots(next);
    writeBistBrief(next);
  }, []);

  const isPickingNew = editing === slots.length;

  return (
    <section aria-label="Takip ettiklerin">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="label">Takip listem</h2>
        {slots.length < MAX_BIST_BRIEF && (
          <button
            type="button"
            onClick={() => setEditing(slots.length)}
            className="flex items-center gap-1 text-2xs text-fg-subtle transition-colors hover:text-fg"
          >
            <Plus className="h-3 w-3" />
            Enstrüman ekle
          </button>
        )}
      </div>

      <div className="flex flex-col gap-3 lg:h-[372px] lg:flex-row">
        {slots.map((slot, index) => {
          const key = slotKey(slot);
          return (
            <div
              key={key}
              className={`min-w-0 grow basis-0 transition-[flex-grow] duration-300 ease-out ${
                expanded === key ? 'lg:grow-[3]' : ''
              }`}
            >
              <BistBriefCard
                slot={slot}
                isExpanded={expanded === key}
                isCollapsed={expanded !== null && expanded !== key}
                onToggle={() => setExpanded((current) => (current === key ? null : key))}
                onEdit={() => setEditing(index)}
              />
            </div>
          );
        })}

        {slots.length === 0 && (
          <button
            type="button"
            onClick={() => setEditing(0)}
            className="surface flex h-[180px] w-full flex-col items-center justify-center gap-1.5 text-fg-subtle transition-colors hover:text-fg"
          >
            <Plus className="h-4 w-4" />
            <span className="text-xs">Takip etmek istediğin bir hisse veya fon seç</span>
          </button>
        )}
      </div>

      <BistBriefPicker
        isOpen={editing !== null}
        current={editing !== null ? (slots[editing] ?? null) : null}
        taken={slots}
        onClose={() => setEditing(null)}
        onPick={(slot) => {
          if (editing === null) return;
          commit(isPickingNew ? addBistSlot(slots, slot) : setBistSlot(slots, editing, slot));
        }}
        onRemove={
          isPickingNew || editing === null
            ? undefined
            : () => {
                const removed = slots[editing];
                if (removed && expanded === slotKey(removed)) setExpanded(null);
                commit(setBistSlot(slots, editing, null));
              }
        }
      />
    </section>
  );
}
