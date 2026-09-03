'use client';

import type { BistSector } from '@/lib/bist-api';
import { formatCompactTry, formatSignedPercent } from '@/lib/bist-format';

/**
 * Where the money actually is, sized by how much of it there is.
 *
 * A sector list ranked by day change tells the reader which sector moved most
 * and hides the fact that it may be two percent of the exchange. Weighting each
 * band by market capitalisation puts that back: on Borsa İstanbul a handful of
 * sectors carry most of the index, and a red band that occupies a third of the
 * strip is a different day from a red band the width of a fingernail.
 *
 * The tint is the day's change and it saturates at `FULL_MOVE`. Beyond that a
 * deeper colour would encode nothing a reader can name — the daily price limit
 * is ten percent per share and a whole sector never approaches it.
 */

/** Where the tint reaches full strength. Roughly a strong sector day. */
const FULL_MOVE = 0.025;

function tintOf(change: number | null): string {
  if (change === null || !Number.isFinite(change) || change === 0) {
    return 'color-mix(in srgb, var(--fg-subtle) 14%, transparent)';
  }
  const strength = Math.min(1, Math.abs(change) / FULL_MOVE);
  // Floored at 28%: a sector that moved a tenth of a percent still has to be
  // distinguishable from one that did not trade, and a band that pales into the
  // paper reads as a loading state rather than as a flat day.
  const alpha = Math.round((0.28 + 0.62 * strength) * 100);
  const hue = change > 0 ? 'var(--borsa-nominal-ink)' : 'var(--borsa-real-loss)';
  return `color-mix(in srgb, ${hue} ${alpha}%, var(--bg))`;
}

export default function SectorStrip({ sectors }: { sectors: readonly BistSector[] }) {
  const shown = [...sectors]
    .filter((sector) => sector.weight > 0)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 12);

  if (shown.length === 0) return null;

  const covered = shown.reduce((sum, sector) => sum + sector.weight, 0);

  return (
    <div className="borsa-sectors">
      <div className="borsa-sector-strip">
        {shown.map((sector) => (
          <span
            key={sector.sector}
            className="borsa-sector-band"
            style={{ flexGrow: sector.weight, background: tintOf(sector.change_pct) }}
            title={`${sector.sector} · ${formatSignedPercent(sector.change_pct)} · ${formatCompactTry(sector.market_cap)}`}
          >
            <span className="borsa-sector-band-label">{sector.sector}</span>
          </span>
        ))}
      </div>

      <ul className="borsa-sector-legend">
        {shown.slice(0, 6).map((sector) => (
          <li key={sector.sector} className="borsa-sector-legend-row">
            <span
              className="borsa-sector-chip"
              aria-hidden="true"
              style={{ background: tintOf(sector.change_pct) }}
            />
            <span className="borsa-sector-name">{sector.sector}</span>
            <span
              className="borsa-figure borsa-sector-change"
              data-down={(sector.change_pct ?? 0) < 0 ? '' : undefined}
            >
              {formatSignedPercent(sector.change_pct)}
            </span>
          </li>
        ))}
      </ul>

      <p className="borsa-label mt-3">
        Bant genişliği piyasa değeri payı · gösterilen {shown.length} sektör toplamın %
        {Math.round(covered * 100)}&apos;i
      </p>
    </div>
  );
}
