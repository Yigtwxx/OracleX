'use client';

import type { AssetBriefLiquidity } from '@/lib/api';
import { formatPrice } from '@/components/overview/overview-utils';
import { formatCompact, formatSignedPercent } from '@/lib/asset-brief';

interface LiquidityLadderProps {
  liquidity: AssetBriefLiquidity;
  /** Spot, so the ladder can put the reader's position in the book. */
  price: number;
}

/**
 * Where leverage is stacked around spot, as a price ladder.
 *
 * Read top-down like an order book: shorts get liquidated above the current
 * price, longs below, and the row widths are notional. The spot marker between
 * them is what makes the two halves mean anything — a wall is only interesting
 * relative to how far price has to travel to reach it.
 *
 * The bars are scaled against the largest cluster on the card rather than
 * against the book's own total. Scaling to the total would leave every bar a
 * few pixels wide on a symbol whose book is spread thin, which is the case this
 * chart most needs to show clearly.
 *
 * The footnote is not boilerplate. These are levels a model deposits from open
 * interest and leverage tiers, not liquidations that were observed, and the two
 * look identical once drawn.
 */
export default function LiquidityLadder({ liquidity, price }: LiquidityLadderProps) {
  const { clusters } = liquidity;
  if (!clusters.length) return null;

  const peak = Math.max(...clusters.map((cluster) => cluster.notional_usd));
  // Highest price at the top, so the ladder reads the way a book is quoted.
  const above = clusters
    .filter((cluster) => cluster.price > price)
    .sort((a, b) => b.price - a.price);
  const below = clusters
    .filter((cluster) => cluster.price <= price)
    .sort((a, b) => b.price - a.price);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="label">Liquidity</span>
        <span className="text-2xs text-fg-subtle">{liquidity.venue ?? 'modelled'}</span>
      </div>

      <div className="mt-1.5 space-y-0.5">
        {above.map((cluster) => (
          <Row key={`${cluster.side}-${cluster.price}`} cluster={cluster} peak={peak} />
        ))}

        {/* Spot. The one row that is a measurement rather than a model. */}
        <div className="flex items-center gap-2 py-0.5">
          <span className="w-[68px] shrink-0 font-mono text-2xs tabnum text-fg">
            {formatPrice(price)}
          </span>
          <span className="h-px flex-1 bg-line-strong" aria-hidden />
          <span className="shrink-0 text-2xs text-fg-subtle">spot</span>
        </div>

        {below.map((cluster) => (
          <Row key={`${cluster.side}-${cluster.price}`} cluster={cluster} peak={peak} />
        ))}
      </div>

      <p className="mt-1.5 text-2xs text-fg-subtle">
        Modelled from open interest, not observed liquidations.
      </p>
    </div>
  );
}

function Row({
  cluster,
  peak,
}: {
  cluster: AssetBriefLiquidity['clusters'][number];
  peak: number;
}) {
  // Longs liquidating is selling pressure and shorts liquidating is buying, so
  // the colour follows what the level would do to price, not which side loses.
  const isLong = cluster.side === 'long';
  const colour = isLong ? 'var(--down)' : 'var(--up)';
  const width = peak > 0 ? Math.max(4, (cluster.notional_usd / peak) * 100) : 0;

  return (
    <div
      className="flex items-center gap-2"
      title={`${formatCompact(cluster.notional_usd)} of ${isLong ? 'long' : 'short'} exposure liquidates near ${formatPrice(cluster.price)} (${formatSignedPercent(cluster.distance_pct, 1)})`}
    >
      <span className="w-[68px] shrink-0 font-mono text-2xs tabnum text-fg-muted">
        {formatPrice(cluster.price)}
      </span>
      <span className="h-1.5 flex-1 overflow-hidden rounded-sm bg-surface-2">
        <span
          className="block h-full rounded-sm"
          style={{ width: `${width}%`, backgroundColor: colour, opacity: 0.65 }}
        />
      </span>
      <span className="w-11 shrink-0 text-right font-mono text-2xs tabnum text-fg-subtle">
        {formatCompact(cluster.notional_usd)}
      </span>
    </div>
  );
}
