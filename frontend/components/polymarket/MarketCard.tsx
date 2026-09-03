import {
  categoryLabel,
  categoryTint,
  formatMoney,
  formatProbability,
  leadingOutcome,
  oddsFraction,
  outcomeColors,
  timeToClose,
} from '@/lib/polymarket-format';
import { memo, useMemo } from 'react';

import type { PolymarketMarket, PolymarketOutcome } from '@/lib/api';

interface MarketCardProps {
  market: PolymarketMarket;
  nowMs: number;
  onOpen: (slug: string) => void;
}

/** How many outcomes fit before the card stops being scannable. */
const MAX_ROWS = 3;

function OutcomeRow({
  outcome,
  leading,
  color,
}: {
  outcome: PolymarketOutcome;
  leading: boolean;
  color: string;
}) {
  const fraction = oddsFraction(outcome.price);

  return (
    <div className="relative">
      {/* The bar sits behind the text rather than beside it, so a row is the
          same height whether or not its outcome has a price. A separate track
          would make unpriced rows visibly shorter and read as less important
          when they are only less known. */}
      {fraction !== null && (
        <div
          className="absolute inset-y-0 left-0 rounded-sm"
          style={{
            width: `${fraction * 100}%`,
            backgroundColor: `color-mix(in srgb, ${color} ${leading ? 20 : 10}%, transparent)`,
          }}
        />
      )}
      <div className="relative flex items-baseline justify-between gap-2 px-1.5 py-1">
        <span className="text-xs truncate" style={{ color }} title={outcome.label}>
          {outcome.label}
        </span>
        <span
          className={`text-xs font-mono tabular-nums shrink-0 ${leading ? 'font-semibold' : ''}`}
          style={{ color }}
        >
          {formatProbability(outcome.price)}
        </span>
      </div>
    </div>
  );
}

/**
 * One market as a card on the board.
 *
 * Outcomes are shown priced rather than as buttons. Polymarket's own cards put a
 * green Yes and a red No under each question because clicking one places a bet;
 * nothing here places a bet, and borrowing that control would offer an action
 * this terminal does not have. The prices carry the same information.
 *
 * The closing time disappears rather than going negative once a market is past
 * its deadline: such a market is awaiting resolution, and "-3d" reads as a
 * countdown running backwards rather than as a state.
 */
function MarketCard({ market, nowMs, onOpen }: MarketCardProps) {
  const closes = timeToClose(market.end_date, nowMs);
  const leader = leadingOutcome(market.outcomes);

  // Keyed on the outcomes rather than recomputed every render: the clock tick
  // that refreshes the countdown would otherwise re-sort and re-colour sixty
  // cards a minute for a result that has not changed.
  const { colors, shown, hidden } = useMemo(() => {
    const ranked = [...market.outcomes].sort((a, b) => (b.price ?? -1) - (a.price ?? -1));
    const visible = ranked.slice(0, MAX_ROWS);
    return {
      colors: outcomeColors(market.outcomes),
      shown: visible,
      hidden: ranked.length - visible.length,
    };
  }, [market.outcomes]);

  const tint = categoryTint(market.category);

  return (
    <button
      type="button"
      onClick={() => onOpen(market.slug)}
      // The border carries the category rather than the shared hairline, so the
      // board can be sorted by eye before a single question is read. Held at low
      // alpha on purpose: at full strength sixty saturated outlines compete with
      // the numbers inside them, which is the opposite of what the colour is for.
      style={{
        borderColor: `color-mix(in srgb, ${tint} 45%, transparent)`,
        boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${tint} 12%, transparent)`,
      }}
      className="surface surface-flat text-left p-3 flex flex-col gap-2.5 transition-colors hover:bg-surface-2 focus:outline-none focus-visible:ring-1"
    >
      <div className="flex items-start gap-2.5">
        {market.icon_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={market.icon_url}
            alt=""
            className="w-8 h-8 rounded shrink-0 object-cover bg-surface-2"
            loading="lazy"
          />
        ) : (
          <div className="w-8 h-8 rounded shrink-0 bg-surface-2" />
        )}
        <span className="text-sm text-fg leading-snug line-clamp-3">{market.question}</span>
      </div>

      <div className="flex flex-col gap-0.5">
        {shown.map((outcome) => (
          <OutcomeRow
            key={outcome.label}
            outcome={outcome}
            leading={leader?.label === outcome.label}
            color={colors[outcome.label] ?? 'var(--fg-muted)'}
          />
        ))}
        {hidden > 0 && (
          <span className="px-1.5 pt-0.5 text-2xs text-fg-subtle">+{hidden} more</span>
        )}
      </div>

      <div className="mt-auto flex items-center gap-2 text-2xs text-fg-subtle tabular-nums">
        <span>{formatMoney(market.volume_usd)} Vol.</span>
        <span aria-hidden="true">·</span>
        <span style={{ color: tint }}>{categoryLabel(market.category)}</span>
        {closes && (
          <>
            <span aria-hidden="true">·</span>
            <span>{closes}</span>
          </>
        )}
      </div>
    </button>
  );
}

/**
 * Memoised because `nowMs` is shared by the whole board: without it one clock
 * tick re-renders every card on the page, and at sixty cards that is a visible
 * stutter for a countdown that changed on three of them.
 */
export default memo(MarketCard);
