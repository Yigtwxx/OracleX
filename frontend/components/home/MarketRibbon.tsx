'use client';

import type { FearGreedData, MarketOverview } from '@/lib/api';
import { formatLargeNumber, getFearGreedColor } from '@/components/overview/overview-utils';

interface MarketRibbonProps {
  marketData: MarketOverview | null;
  fearGreedData: FearGreedData | null;
  isLoading: boolean;
}

/**
 * The six market-wide readings, on one line under the page title.
 *
 * Deliberately a line and not a card grid. This sits where eight on-chain cards
 * used to, and the whole point of that block leaving was that the top of Home
 * should cost a glance rather than a screen — rebuilding it as six cards would
 * have moved the problem rather than solved it.
 *
 * Overview's `MarketStatsBar` shows the same figures in the same colours, which
 * is intended: a reader who learns the palette on one page should not have to
 * relearn it on the other. It is not reused directly because that bar is sticky,
 * carries a refresh control and a session status, and owns the full page width.
 */
export default function MarketRibbon({ marketData, fearGreedData, isLoading }: MarketRibbonProps) {
  if (isLoading && !marketData) {
    return <div className="h-5 w-full max-w-2xl shimmer rounded" aria-hidden />;
  }
  if (!marketData) return null;

  const fg = fearGreedData?.value ?? null;

  return (
    <div className="flex items-center gap-x-3 gap-y-1 flex-wrap text-2xs">
      {fg !== null && (
        // Spelled out rather than initialled. "F&G" is obvious to someone who
        // reads a crypto board daily and opaque to everyone else, and the label
        // is the only thing on this line that says what the number is.
        <Stat label="Fear and Greed">
          <span className="font-mono tabnum font-semibold" style={{ color: getFearGreedColor(fg) }}>
            {fg}
          </span>
          <span className="text-fg-subtle">{fearGreedData?.classification}</span>
          {/* The same track the three dominances carry. The index is a 0–100
              reading and the number alone made the reader hold the scale in
              their head, while every figure beside it was drawn as a length. */}
          <Track percent={fg} color={getFearGreedColor(fg)} />
        </Stat>
      )}

      {/* Three shares, in the order they answer "where is the money". Drawn
          only when the reading is a real one: the service's fallback path fills
          every dominance with 0 when CoinGecko's global endpoint fails, and a
          0.0% BTC or stablecoin share is not something that happens — so an
          `undefined` check alone would let an outage render as a claim. */}
      <Divider />
      <Dominance label="BTC.D" percent={marketData.btc_dominance} color="var(--data-btc)" />
      <Dominance label="ETH.D" percent={marketData.eth_dominance} color="var(--data-eth)" />
      <Dominance label="USDT.D" percent={marketData.usdt_dominance} color="var(--data-usdt)" />

      <Divider />
      <Stat label="MCap">
        <span className="font-mono tabnum text-fg">
          {formatLargeNumber(marketData.total_market_cap)}
        </span>
      </Stat>
      <Stat label="24h Vol">
        <span className="font-mono tabnum text-fg">
          {formatLargeNumber(marketData.total_volume_24h)}
        </span>
      </Stat>
    </div>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="label">{label}</span>
      {children}
    </span>
  );
}

function Divider() {
  return <span className="w-px h-3 bg-line" aria-hidden />;
}

function Dominance({
  label,
  percent,
  color,
}: {
  label: string;
  percent: number | undefined;
  color: string;
}) {
  // A share of exactly zero is the shape an outage takes here, not a market
  // state. See the call site.
  if (percent === undefined || !Number.isFinite(percent) || percent <= 0) return null;

  return (
    <Stat label={label}>
      <span className="font-mono tabnum text-fg">{percent.toFixed(1)}%</span>
      <Track percent={percent} color={color} />
    </Stat>
  );
}

/** A 0–100 reading, as a length. Shared so the F&G bar cannot drift from these. */
function Track({ percent, color }: { percent: number; color: string }) {
  return (
    <span className="w-10 h-1 bg-line rounded-full overflow-hidden" aria-hidden>
      <span
        className="block h-full rounded-full"
        style={{ width: `${Math.min(100, Math.max(0, percent))}%`, backgroundColor: color }}
      />
    </span>
  );
}
