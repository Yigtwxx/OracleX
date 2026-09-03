'use client';

import { AlertTriangle, ChevronDown, SlidersHorizontal } from 'lucide-react';
import Link from 'next/link';

import BriefChart from '@/components/home/BriefChart';
import SparklineChart from '@/components/overview/SparklineChart';
import AiNote from '@/components/ui/AiNote';
import { useBistFund, useBistStock, useBistViop } from '@/hooks/useBist';
import type { FramedReturn } from '@/lib/bist-api';
import {
  EMPTY,
  formatCompact,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  formatTry,
  isRealLoss,
  realReturnNote,
  toneClass,
} from '@/lib/bist-format';
import {
  BIST_TONE_TEXT,
  bandPosition,
  pickViopContract,
  rangeBand,
  rsiBand,
  sharpeBand,
  volumeBand,
  type Band,
  type BistBriefSlot,
} from '@/lib/bist-brief';

/**
 * One followed instrument, as a card.
 *
 * A share and a fund answer different questions and the card does not pretend
 * otherwise: a share has a session, a yearly band and a turnover; a fund prices
 * once a day and is judged on what its return cost to obtain. What they share
 * is the figure this realm exists for — the trailing year read twice — which
 * sits in the same place on both and is the one row comparable across cards.
 *
 * The row is a fixed band so the board below it does not jump when a card
 * expands, which means the tallest state has to **scroll rather than clip**.
 * That is the same shape `components/home/AssetBriefCard.tsx` settled on for
 * the same reason, and the first version of this card learned it the hard way:
 * `overflow-hidden` ate the expanded readings.
 *
 * `BriefChart` and `SparklineChart` come from the crypto board rather than
 * being copied. Neither knows anything about crypto — one takes closes and two
 * optional levels, the other takes closes — and a second copy here would be a
 * second place for the level-clamping rule to drift.
 */

const KIND_LABEL: Record<BistBriefSlot['kind'], string> = {
  stock: 'Hisse',
  fund: 'Fon',
};

function Shell({
  children,
  lit,
}: {
  children: React.ReactNode;
  /** A nominal gain that was a real loss — the one state this board lights. */
  lit?: boolean;
}) {
  return (
    <div
      className={`surface surface-flat h-full min-h-[220px] p-3 ${lit ? 'brief-real-loss' : ''}`}
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
  tone: Band['tone'];
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      title={title}
      className={`rounded border border-line px-1.5 py-0.5 font-mono text-2xs tabnum ${BIST_TONE_TEXT[tone]}`}
    >
      {children}
    </span>
  );
}

function Stat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="min-w-0">
      <p className="label truncate">{label}</p>
      <p className={`tabnum truncate text-sm ${tone ?? 'text-fg'}`}>{value}</p>
    </div>
  );
}

/**
 * The band a price is trading inside, with the price marked on it.
 *
 * The same device the crypto card draws for support and resistance. Here the
 * bounds are the 52-week extremes, which is what a Turkish share has instead:
 * there is no public order-book depth to derive levels from, and inventing two
 * would be a picture of a measurement nobody took.
 */
function RangeBar({
  low,
  high,
  position,
  label,
  decimals = 2,
}: {
  low: number | null;
  high: number | null;
  position: number | null;
  label: string;
  decimals?: number;
}) {
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between gap-2 text-2xs">
        <span className="tabnum font-mono text-up">{formatTry(low, decimals)}</span>
        <span className="label">{label}</span>
        <span className="tabnum font-mono text-down">{formatTry(high, decimals)}</span>
      </div>
      {position !== null ? (
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
            aria-label={`Fiyat, yıllık aralığın %${(position * 100).toFixed(0)} noktasında`}
          />
        </div>
      ) : (
        // One bound missing, or a price outside the band it was measured
        // against — most often a capital action the quote source did not adjust.
        <p className="mt-1.5 text-2xs text-fg-subtle">Fiyat ölçülen aralığın dışında.</p>
      )}
    </div>
  );
}

/**
 * The trailing year, read twice. The one row both kinds share.
 *
 * Each figure sits immediately after its own word rather than in a right-hand
 * column. `ReturnCell` — which every table on this realm uses — stacks the two
 * numbers against a single label, and that works in a dense grid where the
 * column header says what they are. On a card it did not: the header read
 * "nominal / reel" on the left while the two values stacked at the far right
 * edge, so nothing said which of them was which.
 */
function YearRow({
  framed,
  realAvailable,
}: {
  framed: FramedReturn | null;
  realAvailable: boolean;
}) {
  if (!framed) {
    return (
      <div className="mt-3 flex items-baseline gap-2 border-t border-line pt-2.5">
        <span className="label">1 yıl</span>
        <span className="text-sm text-fg-subtle">{EMPTY}</span>
      </div>
    );
  }

  const loss = isRealLoss(framed);

  return (
    <div
      className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-t border-line pt-2.5"
      title={realReturnNote(framed)}
    >
      <span className="label">1 yıl</span>

      <span className="flex items-baseline gap-1.5">
        <span className="label">nominal</span>
        <span className={`tabnum font-mono text-sm ${toneClass(framed.nominal)}`}>
          {formatSignedPercent(framed.nominal)}
        </span>
      </span>

      <span className="flex items-baseline gap-1.5">
        <span className="label">reel</span>
        <span
          className={`tabnum font-mono text-sm ${
            !realAvailable || framed.real === null ? 'text-fg-subtle' : toneClass(framed.real)
          }`}
        >
          {realAvailable && framed.real !== null ? formatSignedPercent(framed.real) : EMPTY}
        </span>
        {loss && (
          // Nominally up, actually down. A marker rather than a colour change,
          // because the colour already encodes direction.
          <span className="text-2xs text-down" aria-label="Nominal kazanç, reel kayıp">
            ▾
          </span>
        )}
      </span>
    </div>
  );
}

function Header({
  kind,
  code,
  name,
  href,
  isExpanded,
  isCollapsed,
  onToggle,
  onEdit,
}: {
  kind: BistBriefSlot['kind'];
  code: string;
  name: string | null;
  href: string;
  isExpanded: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
  onEdit: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={isExpanded}
        aria-label={`${code} kartını ${isExpanded ? 'küçült' : 'genişlet'}`}
        className="min-w-0 flex-1 text-left"
      >
        <span className="flex items-center gap-1.5">
          <span className="label shrink-0">{KIND_LABEL[kind]}</span>
          <span className="truncate text-sm font-semibold text-fg">{code}</span>
          <ChevronDown
            className={`h-3 w-3 shrink-0 text-fg-subtle transition-transform ${
              isExpanded ? 'rotate-180' : ''
            }`}
          />
        </span>
        <span
          className={`mt-0.5 block truncate text-2xs text-fg-subtle ${isCollapsed ? 'lg:hidden' : ''}`}
          title={name ?? undefined}
        >
          {name ?? EMPTY}
        </span>
      </button>

      {/* A quiet zone, and the `stopPropagation` is the point: everything else
          on this card toggles the expand, so a press that landed a few pixels
          off the control would grow the card and slide the control out from
          under the cursor. */}
      <div
        className="-mr-0.5 flex shrink-0 items-center gap-1 p-1"
        onClick={(event) => event.stopPropagation()}
      >
        <Link
          href={href}
          aria-label={`${code} detay sayfası`}
          className="rounded px-1.5 py-0.5 font-mono text-2xs text-fg-subtle transition-colors hover:text-fg"
        >
          Aç
        </Link>
        <button
          type="button"
          onClick={onEdit}
          aria-label={`Bu slotu değiştir (şu an ${code})`}
          className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-2 text-fg-muted transition-colors hover:text-fg"
        >
          <SlidersHorizontal className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

/**
 * The VİOP contract behind a share, where one is listed.
 *
 * Most are not: the board is a few dozen rows across about ten underlyings, so
 * "no listed contract" is the ordinary answer and it is stated rather than left
 * as a gap. A share with a futures line and one without look alike when the
 * line is simply absent, and the reader cannot tell which they are looking at.
 *
 * Funds never reach here. A TEFAS fund has no derivative and never will, so an
 * empty futures slot on a fund card would imply one could exist.
 */
function ViopRow({ underlying }: { underlying: string }) {
  // The whole board, once, shared by every card on the page — the endpoint's
  // own `underlying` filter would be a request per card for the same 49 rows.
  const { data, isLoading } = useBistViop();
  if (isLoading && !data) return null;

  const contract = pickViopContract(data?.contracts, underlying);

  if (!contract) {
    return (
      <p className="mt-3 border-t border-line pt-2.5 text-2xs text-fg-subtle">
        VİOP&apos;ta bu hisseye dayalı sözleşme yok.
      </p>
    );
  }

  return (
    <div className="mt-3 border-t border-line pt-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="label">VİOP · {contract.expiry}</span>
        <span className="flex items-baseline gap-1.5">
          <span className="tabnum font-mono text-sm text-fg">{formatTry(contract.last)}</span>
          <span className={`tabnum font-mono text-2xs ${toneClass(contract.change_pct)}`}>
            {formatSignedPercent(contract.change_pct)}
          </span>
        </span>
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2 text-2xs text-fg-subtle">
        {/* Named for what it is rather than as "front month": the contract is
            chosen by open interest, not by parsing a Turkish expiry string. */}
        <span>En çok açık pozisyonlu sözleşme{contract.physical ? ' · fiziki teslimat' : ''}</span>
        <span className="tabnum font-mono">
          {formatCompact(contract.open_interest, 0)}
          {contract.open_interest_change !== null && (
            <span className={toneClass(contract.open_interest_change)}>
              {' '}
              {contract.open_interest_change >= 0 ? '+' : ''}
              {formatCompact(contract.open_interest_change, 0)}
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

function Failed({ code, onEdit }: { code: string; onEdit: () => void }) {
  return (
    <Shell>
      <div className="flex h-full flex-col items-start justify-center gap-1.5">
        <AlertTriangle className="h-4 w-4 text-fg-subtle" />
        <span className="text-sm font-semibold text-fg">{code}</span>
        <p className="text-2xs text-fg-subtle">
          Bu kod Borsa İstanbul veya TEFAS listelerinde bulunamadı.
        </p>
        <button
          type="button"
          onClick={onEdit}
          className="mt-1 rounded border border-line px-2 py-1 text-2xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
        >
          Başka bir enstrüman seç
        </button>
      </div>
    </Shell>
  );
}

/** The scroller every populated card shares. */
function Scroller({ children }: { children: React.ReactNode }) {
  return (
    <div className="custom-scrollbar flex h-full min-h-0 flex-col overflow-y-auto overflow-x-hidden">
      {children}
    </div>
  );
}

export default function BistBriefCard({
  slot,
  isExpanded,
  isCollapsed,
  onToggle,
  onEdit,
}: {
  slot: BistBriefSlot;
  isExpanded: boolean;
  /** True while some *other* card is expanded, so this one is a narrow column. */
  isCollapsed: boolean;
  onToggle: () => void;
  onEdit: () => void;
}) {
  const isStock = slot.kind === 'stock';
  const stock = useBistStock(isStock ? slot.code : null, '1y');
  const fund = useBistFund(isStock ? null : slot.code, 12);

  const query = isStock ? stock : fund;
  if (query.isLoading) return <div className="surface h-full min-h-[220px] shimmer" aria-hidden />;
  if (query.isError || !query.data) return <Failed code={slot.code} onEdit={onEdit} />;

  if (isStock && stock.data) {
    const row = stock.data;
    const framed = row.returns?.['1y'] ?? null;
    const realAvailable = row.real_return.deflatable_windows.includes('1y');
    const closes = row.candles.map((candle) => candle.close);
    const position = bandPosition(row.price, row.week52_low, row.week52_high);
    const rsi = rsiBand(row.rsi);
    const volume = volumeBand(row.relative_volume);
    const range = rangeBand(position);
    const realLoss = !!framed && framed.nominal > 0 && framed.real !== null && framed.real < 0;

    return (
      <Shell lit={realLoss}>
        <Scroller>
          <Header
            kind="stock"
            code={row.ticker}
            name={row.name}
            href={`/bist/hisseler/${row.ticker}`}
            isExpanded={isExpanded}
            isCollapsed={isCollapsed}
            onToggle={onToggle}
            onEdit={onEdit}
          />

          <div className="mt-2 flex items-baseline gap-2">
            <span className="tabnum font-mono text-lg text-fg">{formatTry(row.price)}</span>
            <span className={`tabnum font-mono text-xs ${toneClass(row.change_pct)}`}>
              {formatSignedPercent(row.change_pct)}
            </span>
          </div>

          {closes.length > 1 &&
            (isExpanded ? (
              <div className="mt-3 h-[120px]">
                <BriefChart
                  data={closes}
                  positive={(row.perf_1y ?? row.change_pct ?? 0) >= 0}
                  support={row.week52_low}
                  resistance={row.week52_high}
                />
              </div>
            ) : (
              <div className="mt-2 [&>svg]:h-8 [&>svg]:w-full">
                <SparklineChart
                  data={closes}
                  positive={(row.perf_1y ?? row.change_pct ?? 0) >= 0}
                />
              </div>
            ))}

          {/* Badges. Dropped, not shrunk, on a squeezed card — but only where
              the card is actually squeezed. Below `lg` the strip is a stack of
              full-width cards and there is nothing to save room for. */}
          <div
            className={`mt-2 flex flex-wrap items-center gap-1.5 ${isCollapsed ? 'lg:hidden' : ''}`}
          >
            {rsi && (
              <Badge tone={rsi.tone} title="14 günlük RSI">
                RSI {formatNumber(row.rsi, 0)} · {rsi.label}
              </Badge>
            )}
            {range && <Badge tone={range.tone}>{range.label}</Badge>}
            {volume && (
              <Badge tone={volume.tone} title="Bugünkü hacim, kendi ortalamasına göre">
                Hacim {formatNumber(row.relative_volume, 1)}× · {volume.label}
              </Badge>
            )}
          </div>

          {!isCollapsed && (
            <RangeBar
              label="52 hafta"
              low={row.week52_low}
              high={row.week52_high}
              position={position}
            />
          )}

          <YearRow framed={framed} realAvailable={realAvailable} />

          {!isCollapsed && <ViopRow underlying={row.ticker} />}

          {isExpanded && (
            <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line pt-2.5">
              <Stat label="F/K" value={row.pe !== null ? formatNumber(row.pe, 1) : EMPTY} />
              <Stat label="PD/DD" value={row.pb !== null ? formatNumber(row.pb, 1) : EMPTY} />
              <Stat label="Beta" value={row.beta !== null ? formatNumber(row.beta, 2) : EMPTY} />
              <Stat label="Halka açık" value={formatPercent(row.free_float_pct)} />
              <Stat
                label="Yılbaşı"
                value={formatSignedPercent(row.perf_ytd)}
                tone={toneClass(row.perf_ytd)}
              />
              <Stat label="Sektör" value={<span className="text-2xs">{row.sector}</span>} />
            </div>
          )}

          {!isCollapsed && (
            <div className="mt-3 border-t border-line pt-2.5">
              <AiNote aiNote={row.ai_note} />
            </div>
          )}
        </Scroller>
      </Shell>
    );
  }

  if (!isStock && fund.data) {
    const row = fund.data;
    const framed = row.framed_returns?.['1y'] ?? null;
    const realAvailable = row.real_return.deflatable_windows.includes('1y');
    const closes = row.series.map((point) => point.price);
    const last = closes.length ? closes[closes.length - 1] : null;
    const sharpe = sharpeBand(row.metrics.sharpe);
    const realLoss = !!framed && framed.nominal > 0 && framed.real !== null && framed.real < 0;

    // A fund has no 52-week quote range published against it, but it has its own
    // net asset values — so the same device is drawn from the series the card is
    // already holding rather than left off because the field is missing.
    const low = closes.length ? Math.min(...closes) : null;
    const high = closes.length ? Math.max(...closes) : null;
    const position = bandPosition(last, low, high);

    return (
      <Shell lit={realLoss}>
        <Scroller>
          <Header
            kind="fund"
            code={row.code}
            name={row.title}
            href={`/bist/fonlar/${row.code}`}
            isExpanded={isExpanded}
            isCollapsed={isCollapsed}
            onToggle={onToggle}
            onEdit={onEdit}
          />

          <div className="mt-2 flex items-baseline gap-2">
            {/* Five decimals: a fund unit is priced in fractions of a lira and
                rounding it to two prints the same figure for weeks. */}
            <span className="tabnum font-mono text-lg text-fg">{formatTry(last, 5)}</span>
            <span className="truncate text-2xs text-fg-subtle" title={row.umbrella}>
              {row.umbrella}
            </span>
          </div>

          {closes.length > 1 &&
            (isExpanded ? (
              <div className="mt-3 h-[120px]">
                <BriefChart
                  data={closes}
                  positive={(framed?.nominal ?? 0) >= 0}
                  support={null}
                  resistance={null}
                />
              </div>
            ) : (
              <div className="mt-2 [&>svg]:h-8 [&>svg]:w-full">
                <SparklineChart data={closes} positive={(framed?.nominal ?? 0) >= 0} />
              </div>
            ))}

          <div
            className={`mt-2 flex flex-wrap items-center gap-1.5 ${isCollapsed ? 'lg:hidden' : ''}`}
          >
            {row.risk_value !== null && (
              <Badge tone="neutral" title="TEFAS'ın kendi risk derecesi">
                Risk {row.risk_value}/7
              </Badge>
            )}
            {sharpe && (
              <Badge tone={sharpe.tone} title="Birim riske düşen getiri">
                Sharpe {formatNumber(row.metrics.sharpe, 2)} · {sharpe.label}
              </Badge>
            )}
            {row.metrics.max_drawdown !== null && (
              <Badge tone="down" title="Tepe noktasından dibe">
                Maks. düşüş {formatPercent(row.metrics.max_drawdown)}
              </Badge>
            )}
          </div>

          {!isCollapsed && (
            <RangeBar
              label="1 yıllık aralık"
              low={low}
              high={high}
              position={position}
              decimals={4}
            />
          )}

          <YearRow framed={framed} realAvailable={realAvailable} />

          {/* Always on, not only when expanded. A fund has no session and no
              order book, so without these the card's lower half was empty while
              the share beside it carried a range bar and a futures line — and
              the emptiness read as missing data rather than as a fund. */}
          {!isCollapsed && (
            <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line pt-2.5">
              <Stat
                label="Volatilite"
                value={formatPercent(row.metrics.volatility)}
                tone="text-fg-muted"
              />
              <Stat
                label="Toparlanma"
                value={
                  row.metrics.recovery_days !== null
                    ? `${row.metrics.recovery_days} gün`
                    : 'toparlanmadı'
                }
                tone={row.metrics.recovery_days === null ? 'text-down' : undefined}
              />
              <Stat
                label="Kategori"
                value={
                  row.category_rank !== null && row.category_size !== null
                    ? `${row.category_rank}. / ${row.category_size}`
                    : EMPTY
                }
              />
            </div>
          )}

          {isExpanded && (
            <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line pt-2.5">
              <Stat
                label="Sortino"
                value={row.metrics.sortino !== null ? formatNumber(row.metrics.sortino, 2) : EMPTY}
                tone={toneClass(row.metrics.sortino)}
              />
              <Stat
                label="Calmar"
                value={row.metrics.calmar !== null ? formatNumber(row.metrics.calmar, 2) : EMPTY}
                tone={toneClass(row.metrics.calmar)}
              />
              <Stat label="İşlem" value={row.tradable ? 'Açık' : 'Kapalı'} />
              <Stat label="Gözlem" value={`${row.metrics.observations} gün`} />
              <Stat label="Şemsiye" value={<span className="text-2xs">{row.umbrella}</span>} />
              <Stat label="Risk" value={row.risk_value !== null ? `${row.risk_value}/7` : EMPTY} />
            </div>
          )}

          {!isCollapsed && (
            <div className="mt-3 border-t border-line pt-2.5">
              <AiNote aiNote={row.ai_note} />
            </div>
          )}
        </Scroller>
      </Shell>
    );
  }

  return <Failed code={slot.code} onEdit={onEdit} />;
}
