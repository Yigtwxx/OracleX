'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

import { buildDeflation, positionOf } from '@/lib/borsa/deflation';
import type { BistFund } from '@/lib/bist-api';
import { formatSignedPercent } from '@/lib/bist-format';

/**
 * The year's best funds, both ways at once.
 *
 * The page's argument stops being an anecdote here. The hero takes one fund
 * apart; this takes the top of the table the reader would have found anywhere
 * else and draws the second reading beside the first, in the order the other
 * site ranked them. Nothing is re-sorted — the chart adds a column of truth to
 * a list the reader already believes rather than presenting a different list.
 *
 * Each row is a span, not a bar: the right end is what was printed, the left
 * end is what was kept, and the distance between them is the year's inflation
 * expressed in that fund's own return. A bar chart of real returns would make
 * the same numbers and lose the whole point, which is the *gap*.
 */

/** Enough rows to read as a market, few enough to read as a list. */
const ROWS = 14;

export default function DeflationChart({
  funds,
  window: windowKey,
  inflation,
}: {
  funds: readonly BistFund[];
  window: string;
  inflation: number | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setShown(true);
      return;
    }
    if (node.getBoundingClientRect().bottom < 0) {
      setShown(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        setShown(true);
        observer.disconnect();
      },
      { rootMargin: '-5% 0px -10% 0px' }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const scale = buildDeflation(funds, windowKey, ROWS);
  if (scale.rows.length === 0) return null;

  const zeroPercent = scale.zero * 100;

  return (
    <div ref={ref} className="borsa-slope" data-shown={shown ? '' : undefined}>
      <div className="borsa-slope-legend">
        <span className="borsa-slope-key">
          <span className="borsa-slope-swatch borsa-slope-swatch-nominal" aria-hidden="true" />
          Nominal
        </span>
        <span className="borsa-slope-key">
          <span className="borsa-slope-swatch borsa-slope-swatch-real" aria-hidden="true" />
          Reel
        </span>
        {inflation !== null && (
          <span className="borsa-slope-key borsa-slope-key-note">
            Aradaki mesafe: yıllık TÜFE {formatSignedPercent(inflation)}
          </span>
        )}
      </div>

      <ol className="borsa-slope-list">
        {scale.rows.map((row, index) => {
          const nominalAt = positionOf(scale, row.nominal) * 100;
          const realAt = positionOf(scale, row.real) * 100;
          return (
            <li key={row.code} className="borsa-slope-row" style={{ ['--i' as string]: index }}>
              <Link href={`/bist/fonlar`} className="borsa-slope-link">
                <span className="borsa-slope-code borsa-figure">{row.code}</span>
                <span className="borsa-slope-title">{row.title}</span>

                <span
                  className="borsa-slope-track"
                  data-off={row.offScale ? '' : undefined}
                  aria-hidden="true"
                >
                  <span className="borsa-slope-zero" style={{ left: `${zeroPercent}%` }} />
                  <span
                    className="borsa-slope-bar"
                    style={{ left: `${realAt}%`, width: `${Math.max(0, nominalAt - realAt)}%` }}
                  />
                  <span className="borsa-slope-dot-nominal" style={{ left: `${nominalAt}%` }} />
                  <span
                    className="borsa-slope-dot-real"
                    data-loss={row.realLoss ? '' : undefined}
                    style={{ left: `${realAt}%` }}
                  />
                </span>

                <span className="borsa-slope-figures">
                  <span className="borsa-figure borsa-slope-nominal">
                    {formatSignedPercent(row.nominal)}
                  </span>
                  <span
                    className="borsa-figure borsa-slope-real"
                    data-loss={row.realLoss ? '' : undefined}
                  >
                    {formatSignedPercent(row.real)}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>

      {/* The axis, once, rather than a labelled zero line on every row. */}
      <div className="borsa-slope-axis" aria-hidden="true">
        <span className="borsa-slope-axis-track">
          <span className="borsa-slope-axis-zero" style={{ left: `${zeroPercent}%` }}>
            %0
          </span>
        </span>
      </div>

      {/* Say what the frame left out and what it pinned. A chart that caps its
          rows or its axis without mentioning either reads as the whole market
          drawn to its true range, and it is neither. */}
      <p className="borsa-label mt-4">
        İlk {scale.rows.length} fon
        {scale.omitted > 0 && ` · ölçülebilen ${scale.omitted} fon daha listede`}
        {scale.offScale > 0 && ` · ${scale.offScale} satır eksenin dışında, sağ kenara sabitlendi`}
      </p>
    </div>
  );
}
