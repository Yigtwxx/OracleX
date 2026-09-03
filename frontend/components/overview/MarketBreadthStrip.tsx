'use client';

import { useMemo } from 'react';
import { MarketOverview } from '@/lib/api';
import { computeBreadth } from '@/lib/market-breadth';

interface MarketBreadthStripProps {
  marketData: MarketOverview | null;
  marketType: 'crypto' | 'nasdaq';
  isLoading: boolean;
}

const pct = (value: number | null, digits = 2): string =>
  value == null ? '--' : `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;

const toneOf = (value: number | null): string =>
  value == null ? 'text-fg-subtle' : value > 0 ? 'text-up' : value < 0 ? 'text-down' : 'text-fg';

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="surface p-4 flex flex-col">
      <div className="label">{title}</div>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-sm text-fg-muted">{label}</span>
      <span className="text-base font-mono tabnum">{children}</span>
    </div>
  );
}

/** The sentence under each card. Muted on purpose — it explains, it does not shout. */
function Reading({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-auto pt-3 border-t border-line text-2xs leading-relaxed text-fg-subtle">
      {children}
    </p>
  );
}

function Skeleton() {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.35fr_1fr_1fr] gap-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="surface p-4 space-y-3">
          <div className="h-2.5 w-28 rounded bg-surface-2 shimmer" />
          <div className="h-2 w-full rounded-full bg-surface-2 shimmer" />
          <div className="h-3 w-full rounded bg-surface-2 shimmer" />
          <div className="h-3 w-2/3 rounded bg-surface-2 shimmer" />
        </div>
      ))}
    </div>
  );
}

/**
 * How many assets moved, and which way — the reading the stats bar above cannot
 * give. That bar reports totals: market cap, turnover, dominance. Two markets
 * with identical totals can have opposite internals, and this is the strip that
 * tells them apart.
 *
 * Everything here is derived client-side from the payload the page already
 * holds, which is why it can sit under a table of the same 250 rows without
 * costing a request.
 */
export default function MarketBreadthStrip({
  marketData,
  marketType,
  isLoading,
}: MarketBreadthStripProps) {
  const breadth = useMemo(
    () => (marketData?.coins?.length ? computeBreadth(marketData.coins) : null),
    [marketData]
  );

  if (isLoading && !breadth) return <Skeleton />;
  if (!breadth || breadth.total === 0) return null;

  const noun = marketType === 'nasdaq' ? 'stocks' : 'assets';
  const {
    total,
    advancing,
    declining,
    unchanged,
    advancingPct,
    advanceDeclineRatio,
    advancing7d,
    reporting7d,
    medianChange,
    meanChange,
    capWeightedChange,
    medianRangePosition,
    rangeReporting,
    upperHalfCount,
    top10VolumeShare,
  } = breadth;

  // The gap between the two is the story: a mean far from the median means a
  // handful of moves are doing the work. Ratios are only meaningful when the
  // median is actually off zero, so the copy switches rather than dividing.
  const skewed =
    medianChange != null && meanChange != null && Math.abs(meanChange - medianChange) > 0.5;

  // Above this, turnover is not "concentrated in the majors" — it is one row
  // reporting a number the market did not trade.
  const CONCENTRATION_SUSPECT = 95;
  const concentrationSuspect = top10VolumeShare != null && top10VolumeShare > CONCENTRATION_SUSPECT;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.35fr_1fr_1fr] gap-3">
      <Card title="Advance / Decline · 24h">
        <div className="mt-3 flex h-2 rounded-full overflow-hidden bg-surface-2">
          <div style={{ width: `${(advancing / total) * 100}%`, background: 'var(--up)' }} />
          <div style={{ width: `${(declining / total) * 100}%`, background: 'var(--down)' }} />
          <div style={{ width: `${(unchanged / total) * 100}%`, background: 'var(--fg-subtle)' }} />
        </div>

        <div className="mt-2 flex items-baseline justify-between gap-2 text-sm font-mono tabnum">
          <span className="text-up">▲ {advancing}</span>
          {unchanged > 0 && <span className="text-fg-subtle">— {unchanged}</span>}
          <span className="text-down">{declining} ▼</span>
        </div>

        <div className="mt-3 space-y-2">
          {advancing7d != null && (
            <Row label="Advancing over 7d">
              <span className={advancing7d * 2 > reporting7d ? 'text-up' : 'text-down'}>
                {advancing7d} / {reporting7d}
              </span>
            </Row>
          )}
          <Row label="A/D ratio">
            <span className="text-fg">
              {advanceDeclineRatio == null ? 'no decliners' : advanceDeclineRatio.toFixed(2)}
            </span>
          </Row>
        </div>

        <Reading>
          {advancingPct.toFixed(0)}% of the top {total} {noun} advanced
          {marketData?.active_cryptocurrencies && marketType === 'crypto'
            ? ` (of ${marketData.active_cryptocurrencies.toLocaleString('en-US')} tracked)`
            : ''}
          .
        </Reading>
      </Card>

      <Card title="Centre of the move">
        <div className="mt-3 space-y-2">
          <Row label="Median">
            <span className={toneOf(medianChange)}>{pct(medianChange)}</span>
          </Row>
          <Row label="Mean">
            <span className={toneOf(meanChange)}>{pct(meanChange)}</span>
          </Row>
          <Row label="Cap-weighted">
            <span className={toneOf(capWeightedChange)}>{pct(capWeightedChange)}</span>
          </Row>
        </div>

        <Reading>
          {skewed
            ? 'Mean sits well off the median — a few outsized moves are carrying the average. The typical asset did less.'
            : 'Mean and median agree: the move is spread evenly rather than driven by outliers.'}
        </Reading>
      </Card>

      <Card title="Position in 24h range">
        {medianRangePosition == null ? (
          <p className="mt-3 text-base font-mono tabnum text-fg-subtle">--</p>
        ) : (
          <>
            <div
              className="relative mt-4 h-2 rounded-full"
              style={{
                background:
                  'linear-gradient(90deg, var(--down-bg), var(--surface-2), var(--up-bg))',
              }}
              role="img"
              aria-label={`Median asset is trading at ${(medianRangePosition * 100).toFixed(0)}% of its 24h range`}
            >
              <span
                className="absolute -top-1 w-0.5 h-4 rounded-sm bg-fg"
                style={{ left: `${medianRangePosition * 100}%` }}
              />
            </div>
            <div className="mt-1.5 flex justify-between text-2xs font-mono tabnum text-fg-subtle">
              <span>day low</span>
              <span className="text-fg-muted">{(medianRangePosition * 100).toFixed(0)}%</span>
              <span>day high</span>
            </div>

            <div className="mt-3 space-y-2">
              <Row label="Closing upper half">
                <span className="text-fg">
                  {upperHalfCount} / {rangeReporting}
                </span>
              </Row>
              {top10VolumeShare != null && (
                <Row label="Turnover · top 10">
                  <span className={concentrationSuspect ? 'text-warn' : 'text-fg'}>
                    {top10VolumeShare.toFixed(1)}%
                  </span>
                </Row>
              )}
            </div>
          </>
        )}

        <Reading>
          {concentrationSuspect
            ? 'Turnover is almost entirely in ten names — check the volume feed before reading anything into the total.'
            : medianRangePosition != null && medianRangePosition < 0.4
              ? 'The typical asset is trading in the lower part of its day: buyers led, sellers finished.'
              : medianRangePosition != null && medianRangePosition > 0.6
                ? 'Most assets are holding the upper part of their day — the move is being defended.'
                : 'Assets are sitting mid-range; the day has no clear close.'}
        </Reading>
      </Card>
    </div>
  );
}
