'use client';

import { RefreshCw } from 'lucide-react';
import { MarketOverview, FearGreedData } from '@/lib/api';
import { formatLargeNumber, getFearGreedColor } from './overview-utils';

interface MarketStatsBarProps {
  marketData: MarketOverview | null;
  fearGreedData: FearGreedData | null;
  marketType: 'crypto' | 'nasdaq';
  isLoading: boolean;
  lastUpdate: Date | null;
  onRefresh: () => void;
}

function Divider() {
  return <div className="w-px h-4 bg-line" />;
}

/**
 * The API prefixes the session message with a coloured emoji ("🟠 Pre-market
 * …"). This bar already draws its own status dot in the same colour, so the
 * emoji arrives as a second, far larger ball beside it. Strips a leading run of
 * pictographic characters and keeps the words.
 *
 * Surrogate pairs are matched explicitly rather than with a `\p{...}` escape,
 * which would need a higher compile target than this project builds against.
 */
const LEADING_EMOJI = new RegExp(
  // A surrogate pair (everything above the BMP, where the coloured circles
  // live), or a BMP symbol/arrow, or a variation selector — one or more of
  // them at the very start, plus the space that follows.
  '^(?:[\\uD800-\\uDBFF][\\uDC00-\\uDFFF]|[\\u2190-\\u2BFF]|\\uFE0F)+\\s*'
);

const stripLeadingEmoji = (message: string): string => message.replace(LEADING_EMOJI, '');

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="label">{label}</span>
      {children}
    </div>
  );
}

/** Inline share bar. Colour identifies the asset, not a mood. */
function DominanceBar({ percent, color }: { percent: number; color: string }) {
  return (
    <div className="w-14 h-1 bg-line rounded-full overflow-hidden">
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${Math.min(100, Math.max(0, percent))}%`, backgroundColor: color }}
      />
    </div>
  );
}

// Explicit class pairs — Tailwind only emits classes it can find as literals,
// so these must never be built by string manipulation.
const STATUS_STYLE: Record<string, { text: string; dot: string }> = {
  green: { text: 'text-up', dot: 'bg-up' },
  orange: { text: 'text-warn', dot: 'bg-warn' },
  blue: { text: 'text-fg-muted', dot: 'bg-fg-muted' },
};
const STATUS_STYLE_FALLBACK = { text: 'text-down', dot: 'bg-down' };

export default function MarketStatsBar({
  marketData,
  fearGreedData,
  marketType,
  isLoading,
  lastUpdate,
  onRefresh,
}: MarketStatsBarProps) {
  const status = marketData?.market_status;
  const statusStyle = status
    ? (STATUS_STYLE[status.color] ?? STATUS_STYLE_FALLBACK)
    : STATUS_STYLE_FALLBACK;

  return (
    <div className="sticky top-0 z-10 bg-bg/95 backdrop-blur-sm border-b border-line">
      <div className="max-w-[1800px] mx-auto px-4 py-2.5">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 flex-wrap">
            <Stat label="Market Cap">
              <span className="text-base font-mono tabnum text-fg">
                {marketData ? formatLargeNumber(marketData.total_market_cap) : '--'}
              </span>
            </Stat>

            <Divider />

            <Stat label="24h Volume">
              <span className="text-base font-mono tabnum text-fg">
                {marketData ? formatLargeNumber(marketData.total_volume_24h) : '--'}
              </span>
            </Stat>

            {marketType === 'crypto' && (
              <>
                <Divider />
                <Stat label="BTC Dom">
                  <span className="text-base font-mono tabnum text-fg">
                    {marketData ? `${marketData.btc_dominance.toFixed(1)}%` : '--'}
                  </span>
                  {marketData && (
                    <DominanceBar percent={marketData.btc_dominance} color="var(--data-btc)" />
                  )}
                </Stat>

                <Divider />
                <Stat label="ETH Dom">
                  <span className="text-base font-mono tabnum text-fg">
                    {marketData?.eth_dominance ? `${marketData.eth_dominance.toFixed(1)}%` : '--'}
                  </span>
                  {/* Same scale as the BTC bar beside it. It used to be drawn
                      at 4x, presumably so a ~10% share was not a sliver — but
                      two share bars sitting side by side are read against each
                      other, and at 4x a 10% ETH matched a 40% BTC. */}
                  {marketData?.eth_dominance != null && (
                    <DominanceBar percent={marketData.eth_dominance} color="var(--data-eth)" />
                  )}
                </Stat>
              </>
            )}

            {marketType === 'nasdaq' && status && (
              <>
                <Divider />
                <div className="flex items-center gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`} />
                  <span className={`text-base ${statusStyle.text}`}>
                    {stripLeadingEmoji(status.message)}
                  </span>
                </div>
              </>
            )}

            <Divider />

            <Stat label="Fear / Greed">
              <span
                className="text-base font-mono tabnum"
                style={{
                  color: fearGreedData
                    ? getFearGreedColor(fearGreedData.value)
                    : 'var(--fg-subtle)',
                }}
              >
                {fearGreedData ? fearGreedData.value : '--'}
              </span>
            </Stat>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            {lastUpdate && (
              <span className="text-xs font-mono tabnum text-fg-subtle">
                {lastUpdate.toLocaleTimeString('en-GB', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            )}
            <button
              onClick={onRefresh}
              disabled={isLoading}
              aria-label="Refresh market data"
              className="flex items-center gap-1.5 px-2.5 py-1 bg-surface border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
