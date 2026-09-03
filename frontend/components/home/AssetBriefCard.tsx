'use client';

import { ChevronDown, Pencil, TrendingDown, TrendingUp } from 'lucide-react';
import AiNote from '@/components/ui/AiNote';
import AssetLogo from '@/components/ui/AssetLogo';
import BriefChart from './BriefChart';
import LiquidityLadder from './LiquidityLadder';
import SparklineChart from '@/components/overview/SparklineChart';
import { formatPrice } from '@/components/overview/overview-utils';
import type { AssetBrief } from '@/lib/api';
import {
  TONE_TEXT,
  changeTone,
  formatCompact,
  formatSignedPercent,
  fundingReading,
  rangePosition,
  relativeVolumeLabel,
  rsiLabel,
  surgeHue,
  type Surge,
} from '@/lib/asset-brief';

interface AssetBriefCardProps {
  symbol: string;
  brief: AssetBrief | undefined;
  isLoading: boolean;
  error: unknown;
  /** Expanded cards draw the levels and the note; collapsed ones cannot fit them. */
  isExpanded: boolean;
  /** True while some *other* card is expanded, so this one is a narrow column. */
  isCollapsed: boolean;
  onToggle: () => void;
  onEdit: () => void;
}

/**
 * One asset in the Home strip.
 *
 * The card has three widths — equal third, expanded, squeezed — and the same
 * data has to stay honest in all of them. Rather than three layouts, everything
 * below the price is gated on which width the card currently has: a squeezed
 * card drops the badges and the note instead of shrinking them into
 * illegibility, and an expanded one earns the range bar and the levels.
 */
export default function AssetBriefCard({
  symbol,
  brief,
  isLoading,
  error,
  isExpanded,
  isCollapsed,
  onToggle,
  onEdit,
}: AssetBriefCardProps) {
  if (error) {
    return (
      <Shell>
        <div className="flex h-full flex-col items-start justify-center gap-1.5">
          <span className="text-sm font-semibold text-fg">{symbol}</span>
          <p className="text-2xs text-fg-subtle">
            Could not resolve this symbol. Check the ticker, or pick another asset.
          </p>
          <button
            onClick={onEdit}
            className="mt-1 rounded border border-line px-2 py-1 text-2xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
          >
            Change asset
          </button>
        </div>
      </Shell>
    );
  }

  if (isLoading || !brief) {
    return <div className="surface h-full min-h-[200px] shimmer" aria-hidden />;
  }

  const tone = changeTone(brief.change_24h_pct);
  const rsi = rsiLabel(brief.rsi_14);
  const funding = brief.crypto
    ? fundingReading(brief.crypto.funding_rate, brief.crypto.funding_is_extreme)
    : null;
  const volume = brief.equity ? relativeVolumeLabel(brief.equity.relative_volume) : null;
  const position = rangePosition(brief);
  const Arrow = tone === 'down' ? TrendingDown : TrendingUp;
  const surge = surgeHue(brief.change_24h_pct, brief.change_7d_pct);

  return (
    <Shell surge={surge} onActivate={onToggle}>
      {/* The row is a fixed height so the three cards align, which means the
          tallest state has to scroll rather than clip. It used to clip: an
          expanded card cut its note off mid-sentence and offered nothing to
          drag. `min-h-0` is what lets a flex child actually shrink enough to
          give the scroller something to scroll. */}
      <div className="flex h-full min-h-0 flex-col overflow-y-auto overflow-x-hidden custom-scrollbar">
        {/* Header: identity, and the two controls. The edit button is separate
            from the expand toggle because they are opposite intents — one asks
            for more of this asset, the other replaces it. */}
        <div className="flex items-start justify-between gap-2">
          <button
            onClick={onToggle}
            className="min-w-0 flex-1 text-left"
            aria-expanded={isExpanded}
            aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${brief.display_symbol}`}
          >
            <span className="flex items-center gap-1.5">
              <span className="truncate text-sm font-semibold text-fg">{brief.display_symbol}</span>
              <ChevronDown
                className={`h-3 w-3 shrink-0 text-fg-subtle transition-transform ${
                  isExpanded ? 'rotate-180' : ''
                }`}
              />
            </span>
            <span
              className={`mt-0.5 block truncate text-2xs text-fg-subtle ${
                isCollapsed ? 'lg:hidden' : ''
              }`}
            >
              {brief.equity?.name ?? (brief.asset_type === 'crypto' ? 'Crypto' : 'Equity')}
            </span>
          </button>
          {/* The corner is a quiet zone, and the `stopPropagation` is the point
              of it. Everything else on this card toggles the expand, so a press
              that landed a few pixels off the pencil used to grow the card and
              slide the pencil out from under the cursor — the miss moved the
              target, which is what made a second attempt harder than the first.
              Inside this box a miss now does nothing at all. */}
          <div
            className="-mr-0.5 flex shrink-0 items-center gap-2 p-1"
            onClick={(event) => event.stopPropagation()}
          >
            {/* The asset's own mark, in the corner the header left empty.
                Decorative — the symbol is spelled out beside it. The fallback
                chain lives in `AssetLogo`, which is why nothing here knows
                which host answered. */}
            <AssetLogo
              symbol={brief.display_symbol}
              marketType={brief.asset_type === 'crypto' ? 'crypto' : 'nasdaq'}
              className="h-7 w-7 rounded-full bg-surface-2 object-cover"
            />
            {/* Sized and filled like the mark beside it rather than left as a
                bare glyph. A 12px hint on a 20px box was something to aim at;
                a 28px chip is something to press, and it reads as a control
                before the cursor gets there. */}
            <button
              onClick={onEdit}
              aria-label={`Change the asset in this slot (currently ${brief.display_symbol})`}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-2 text-fg-muted transition-colors hover:text-fg"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Price */}
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-mono text-lg tabnum text-fg">{formatPrice(brief.price)}</span>
          <span className={`flex items-center gap-0.5 text-xs font-mono tabnum ${TONE_TEXT[tone]}`}>
            <Arrow className="h-3 w-3" />
            {formatSignedPercent(brief.change_24h_pct)}
          </span>
        </div>
        {brief.change_7d_pct !== null && (
          <span
            className={`mt-0.5 block text-2xs text-fg-subtle ${isCollapsed ? 'lg:hidden' : ''}`}
          >
            7d {formatSignedPercent(brief.change_7d_pct, 1)}
          </span>
        )}

        {/* Series. Expanded, the same closes become a chart with the levels
            drawn on them; collapsed, they stay a sparkline stretched to the
            card's width rather than the SVG's own 100 units, so the line reads
            the same at every column width. */}
        {brief.spark.length > 1 &&
          (isExpanded ? (
            <div className="mt-3 h-[120px]">
              <BriefChart
                data={brief.spark}
                positive={tone !== 'down'}
                support={brief.support}
                resistance={brief.resistance}
              />
            </div>
          ) : (
            <div className="mt-2 [&>svg]:h-8 [&>svg]:w-full">
              <SparklineChart data={brief.spark} positive={tone !== 'down'} />
            </div>
          ))}

        {/* Badges. Dropped, not shrunk, on a squeezed card — but only where
            the card is actually squeezed. Below `lg` the strip is a stack of
            full-width cards and there is nothing to save room for. */}
        <div
          className={`mt-2 flex flex-wrap items-center gap-1.5 ${isCollapsed ? 'lg:hidden' : ''}`}
        >
          {rsi && (
            <Badge
              tone={rsi.tone}
              title={`RSI ${brief.rsi_14?.toFixed(1)} on ${brief.timeframe ?? 'the primary timeframe'}`}
            >
              RSI {brief.rsi_14?.toFixed(0)} · {brief.rsi_signal ?? rsi.label}
            </Badge>
          )}
          {brief.trend && <Badge tone="neutral">{brief.trend}</Badge>}
          {funding && (
            <Badge
              tone={funding.tone}
              title={`${funding.label} every ${brief.crypto?.funding_interval_hours ?? 8}h`}
            >
              {funding.bps >= 0 ? '+' : ''}
              {funding.bps.toFixed(1)} bps
              {funding.extreme && ' ⚠'}
            </Badge>
          )}
          {volume && (
            <Badge tone={volume.tone} title="Today's volume against its 30-session average">
              Vol {brief.equity?.relative_volume?.toFixed(1)}x · {volume.label}
            </Badge>
          )}
          {/* A perp that does not exist is said outright. An absent badge
                beside three present ones reads as a rate of zero. */}
          {brief.crypto && !funding && <Badge tone="neutral">No listed perp</Badge>}
        </div>

        {/* Levels — only where there is width to label them. */}
        {!isCollapsed && (brief.support !== null || brief.resistance !== null) && (
          <div className="mt-3">
            <div className="flex items-baseline justify-between gap-2 text-2xs">
              <span className="font-mono tabnum text-up">
                {brief.support === null ? '—' : formatPrice(brief.support)}
              </span>
              <span className="label">Support · Resistance</span>
              <span className="font-mono tabnum text-down">
                {brief.resistance === null ? '—' : formatPrice(brief.resistance)}
              </span>
            </div>
            {position !== null ? (
              // A 1px hairline with a 40%-opacity gradient was invisible on this
              // surface, and the marker on it had no `translate` so it drifted
              // off the end at the extremes. The track is now solid and the
              // marker is a real handle, centred on its own position.
              <div className="relative mt-2 h-2 rounded-full border border-line bg-surface-2">
                <span
                  className="absolute inset-0 rounded-full opacity-70"
                  style={{
                    background:
                      'linear-gradient(90deg, var(--up) 0%, var(--fg-subtle) 50%, var(--down) 100%)',
                  }}
                  aria-hidden
                />
                <span
                  className="absolute top-1/2 h-3.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-fg ring-2 ring-surface"
                  style={{ left: `${position * 100}%` }}
                  role="img"
                  aria-label={`Price sits ${(position * 100).toFixed(0)}% of the way from support to resistance`}
                />
              </div>
            ) : (
              // Price outside the band it was measured against, or only one
              // bound found. A bar drawn from half a measurement would be a
              // picture of something nobody computed.
              <p className="mt-1.5 text-2xs text-fg-subtle">Price is outside the measured band.</p>
            )}
          </div>
        )}

        {/* Where leverage is stacked. Crypto only — the liquidation book is
            modelled from perpetual open interest, and US equities have no
            equivalent public feed, so an equity card shows its 52-week range
            in the same slot rather than an empty one. */}
        {!isCollapsed && brief.crypto?.liquidity && (
          <div className="mt-3 border-t border-line pt-2.5">
            <LiquidityLadder liquidity={brief.crypto.liquidity} price={brief.price} />
          </div>
        )}
        {!isCollapsed && brief.equity && <YearRange brief={brief} />}

        {!isCollapsed && (
          <div className="mt-3 border-t border-line pt-2.5">
            <AiNote aiNote={brief.ai_note} />
          </div>
        )}

        {isExpanded && (
          <div className="mt-3 flex items-baseline justify-between gap-2 text-2xs text-fg-subtle">
            <span>{brief.symbol}</span>
            <span className="font-mono tabnum">
              {brief.crypto
                ? `${formatCompact(brief.crypto.volume_24h_usd)} 24h`
                : `${formatCompact(brief.equity?.volume ?? null, false)} sh`}
            </span>
          </div>
        )}
      </div>
    </Shell>
  );
}

/**
 * The 52-week band, for the asset class that has no liquidation book.
 *
 * Drawn only when price actually sits inside the band. A marker clamped to an
 * edge would say "at its 52-week high" about a stock that had merely been
 * quoted from a different session than its extremes were.
 */
function YearRange({ brief }: { brief: AssetBrief }) {
  const low = brief.equity?.fifty_two_week_low ?? null;
  const high = brief.equity?.fifty_two_week_high ?? null;
  if (low === null || high === null || !(high > low)) return null;

  const inside = brief.price >= low && brief.price <= high;

  return (
    <div className="mt-3 border-t border-line pt-2.5">
      <span className="label">52-week range</span>
      <div className="mt-1.5 flex items-baseline justify-between gap-2 text-2xs">
        <span className="font-mono tabnum text-fg-muted">{formatPrice(low)}</span>
        <span className="font-mono tabnum text-fg-muted">{formatPrice(high)}</span>
      </div>
      {inside ? (
        <div className="relative mt-1 h-2 rounded-full border border-line bg-surface-2">
          {/* The stretch of the band price has already covered, filled rather
              than left as empty track: the distance from the 52-week low is the
              half of this reading a reader actually measures against, and an
              unfilled bar makes it something they have to estimate from a
              marker's position. Accent blue, not green or red — how far up its
              own year a stock sits is not a direction. */}
          {/* Not `bg-accent/45`. These colour tokens are bare `var(--…)` values
              with no `<alpha-value>` placeholder, so Tailwind 3's `/45` opacity
              modifier compiles to an invalid colour and the element renders with
              no background at all — which is exactly how this bar, and the
              support/resistance bar before it, ended up invisible. Anything that
              needs a tint on these tokens sets it explicitly. */}
          <span
            className="absolute inset-y-0 left-0 rounded-full"
            style={{
              width: `${((brief.price - low) / (high - low)) * 100}%`,
              background: 'var(--accent-soft)',
            }}
            aria-hidden
          />
          <span
            className="absolute top-1/2 h-3.5 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-fg ring-2 ring-surface"
            style={{ left: `${((brief.price - low) / (high - low)) * 100}%` }}
            role="img"
            aria-label={`Price sits ${(((brief.price - low) / (high - low)) * 100).toFixed(0)}% of the way up its 52-week band`}
          />
        </div>
      ) : (
        <p className="mt-1 text-2xs text-fg-subtle">Price is outside its own 52-week band.</p>
      )}
    </div>
  );
}

/**
 * The card's frame, and — where `onActivate` is given — its click target.
 *
 * The whole box expands, not just the chevron. The chevron stays because it is
 * the affordance that says the card *can* expand, and it stays a real `<button>`
 * because that is what carries the keyboard path and `aria-expanded`; this
 * handler is the mouse path laid over the top of it.
 *
 * Two things it deliberately ignores. A click that originated inside any button
 * is left alone — the chevron and the edit control have already run their own
 * handlers, and toggling again here would undo the chevron's work and expand the
 * card behind the picker. And a click that ends a text selection is not a click:
 * the note is prose people highlight, and collapsing the card out from under a
 * half-read sentence is the exact thing that makes a surface feel hostile.
 */
function Shell({
  children,
  surge,
  onActivate,
}: {
  children: React.ReactNode;
  surge?: Surge | null;
  onActivate?: () => void;
}) {
  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!onActivate) return;
    if ((event.target as HTMLElement).closest('button, a, input, [role="button"]')) return;
    if (window.getSelection()?.toString()) return;
    onActivate();
  };

  return (
    <div
      onClick={handleClick}
      className={`surface h-full min-h-[200px] overflow-hidden p-3 ${
        onActivate ? 'cursor-pointer' : ''
      } ${surge ? 'surge-rim' : ''}`}
      style={surge ? ({ '--surge-hue': surge.hue } as React.CSSProperties) : undefined}
      // Named rather than left as an unexplained glow, and named with the window
      // it was measured over: a card lit by its week while its day sits flat
      // reads as a bug until the reader is told which figure did it. The
      // direction is spelled out too — a red and a green rim are the same shape
      // to anyone who cannot separate the two.
      title={
        surge
          ? `${surge.direction === 'down' ? 'Down' : 'Up'} ${Math.abs(surge.change).toFixed(1)}% over the last ${surge.window === '24h' ? '24 hours' : '7 days'}`
          : undefined
      }
    >
      {children}
    </div>
  );
}

function Badge({
  tone,
  title,
  children,
}: {
  tone: 'up' | 'down' | 'neutral';
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      title={title}
      className={`rounded border border-line px-1.5 py-0.5 text-2xs font-mono tabnum ${TONE_TEXT[tone]}`}
    >
      {children}
    </span>
  );
}
