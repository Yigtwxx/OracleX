'use client';

import type { Ipo } from '@/lib/bist-api';
import { EMPTY, formatDate, formatSignedPercent, toneClass } from '@/lib/bist-format';
import { type IpoBasis, rankByReturn, unmeasuredCount } from '@/lib/bist-ipo';

/**
 * What each recent offering has returned since it started trading.
 *
 * The board's primary panel, and the only one whose numbers are ours: the
 * offering price comes from the calendar, but the current price is the scanner's
 * and the arithmetic is the backend's. Bars run both ways from a centre line
 * because roughly half of them are negative and a left-anchored chart would
 * hide that behind a sort.
 *
 * DOM rather than ECharts: each row is one bar plus four text fields with no
 * axis interaction, which is `positioning/RangeDistribution`'s shape, and text
 * inside a canvas cannot be selected or reflowed.
 */
export default function IpoReturnRanking({ rows, basis }: { rows: Ipo[]; basis: IpoBasis }) {
  const ranked = rankByReturn(rows, basis);
  const missing = unmeasuredCount(rows, basis);
  const ceiling = Math.max(0.1, ...ranked.map((row) => Math.abs(row.value)));

  return (
    <div className="space-y-2">
      <ul className="custom-scrollbar max-h-[420px] space-y-1.5 overflow-y-auto pr-1">
        {ranked.map((row) => {
          const width = (Math.abs(row.value) / ceiling) * 50;
          const positive = row.value >= 0;
          return (
            <li
              key={row.slug}
              className="grid grid-cols-[4.5rem_1fr_4.5rem] items-center gap-2"
              // A listing days old has a real return that is not yet a track
              // record. Dimmed rather than hidden: excluding it would flatter
              // the distribution by dropping the newest names.
              style={{ opacity: row.seasoned ? 1 : 0.55 }}
            >
              <span className="truncate text-2xs font-medium text-fg" title={row.company}>
                {row.ticker ?? EMPTY}
              </span>

              <span className="relative flex h-3 items-center">
                <span className="absolute inset-y-0 left-1/2 w-px bg-line-strong" aria-hidden />
                <span
                  className={`absolute h-2 rounded-sm ${positive ? 'bg-up' : 'bg-down'}`}
                  style={
                    positive
                      ? { left: '50%', width: `${width}%` }
                      : { right: '50%', width: `${width}%` }
                  }
                />
              </span>

              <span className={`tabnum text-right text-2xs ${toneClass(row.value)}`}>
                {formatSignedPercent(row.value, 0)}
              </span>

              <span className="col-span-3 -mt-0.5 pl-[4.5rem] text-2xs text-fg-subtle">
                {row.price != null && `${row.price} TL arz · `}
                {row.listingDate ? formatDate(row.listingDate) : 'tarih yok'} · {row.daysListed} gün
                {!row.seasoned && ' · sicil için çok yeni'}
              </span>
            </li>
          );
        })}
      </ul>

      {/* Always printed, both halves. The excluded rows stay visible as a
          number even though they are absent as bars. */}
      <p className="border-t border-line pt-1.5 text-2xs text-fg-subtle">
        {ranked.length} ölçüldü · {missing} ölçülemedi
      </p>
    </div>
  );
}
