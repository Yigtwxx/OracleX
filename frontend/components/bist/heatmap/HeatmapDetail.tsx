'use client';

import type { BistHeatmapTile } from '@/lib/bist-api';
import {
  CAPITAL_ACTION_NOTE,
  EMPTY,
  formatCompact,
  formatCompactTry,
  formatSignedPercent,
  formatTry,
  isLikelyCapitalAction,
  toneClass,
} from '@/lib/bist-format';

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="label">{label}</dt>
      <dd className="tabnum truncate text-sm text-fg">{value}</dd>
    </div>
  );
}

/**
 * The selected company, spelled out under the board.
 *
 * Mounted even with nothing selected. An `aria-live` region that appears only
 * once it has something to say is not announced at all — the region has to be
 * in the document before the text lands in it.
 */
export default function HeatmapDetail({ tile }: { tile?: BistHeatmapTile }) {
  if (!tile) {
    return (
      <aside
        aria-live="polite"
        aria-label="Seçili hisse"
        className="shrink-0 border-t border-line bg-surface px-3 py-2"
      >
        <p className="text-2xs text-fg-subtle">
          Bir kutuya tıklayın ya da klavyeyle odaklanın — şirketin detayı burada görünür.
        </p>
      </aside>
    );
  }

  return (
    <aside
      aria-live="polite"
      aria-label="Seçili hisse"
      className="shrink-0 border-t border-line bg-surface px-3 py-2"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm font-semibold text-fg">
          {tile.ticker} <span className="text-2xs font-normal text-fg-muted">{tile.name}</span>
        </h3>
        <span className={`tabnum text-sm font-medium ${toneClass(tile.change_pct)}`}>
          {formatSignedPercent(tile.change_pct)}
        </span>
        {isLikelyCapitalAction(tile.change_pct) && (
          <span
            title={CAPITAL_ACTION_NOTE}
            className="rounded border border-line px-1.5 text-2xs text-fg-muted"
          >
            sermaye işlemi olabilir
          </span>
        )}
        {tile.indices.length > 0 && (
          // Capped, because the scanner returns every index a name belongs to
          // and a bank belongs to seventeen — XU100 through X030C, most of them
          // slices nobody reads a stock through. The first few are the headline
          // ones, and the count says the rest are there.
          <span className="text-2xs text-fg-subtle">
            {tile.indices.slice(0, 5).join(' · ')}
            {tile.indices.length > 5 && ` +${tile.indices.length - 5}`}
          </span>
        )}
      </div>

      <dl className="mt-1.5 grid grid-cols-2 gap-x-5 gap-y-1 sm:grid-cols-3 lg:grid-cols-6">
        <Field label="Fiyat" value={formatTry(tile.price)} />
        <Field label="Piyasa değeri" value={formatCompactTry(tile.market_cap)} />
        <Field label="İşlem hacmi" value={formatCompactTry(tile.traded_value)} />
        <Field label="Sektör" value={tile.sector} />
        <Field
          label="Açık pozisyon"
          value={tile.has_futures ? formatCompact(tile.open_interest) : EMPTY}
        />
        <Field
          label="AP değişimi"
          value={
            tile.has_futures
              ? `${formatCompact(tile.open_interest_change)} (${formatSignedPercent(
                  tile.open_interest_change_pct
                )})`
              : EMPTY
          }
        />
      </dl>

      {!tile.has_futures && (
        <p className="mt-1 text-2xs text-fg-subtle">
          Bu hissenin VİOP&apos;ta vadeli kontratı yok.
        </p>
      )}
    </aside>
  );
}
