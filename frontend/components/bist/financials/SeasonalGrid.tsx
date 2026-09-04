'use client';

import type { BistFinancials } from '@/lib/bist-api';
import { type Basis, FIELD_LABELS, seasonalGrid, unitFor } from '@/lib/bist-financials';
import { EMPTY } from '@/lib/bist-format';

/**
 * One field as a year-by-quarter grid.
 *
 * Turkish industrials are strongly seasonal — an airline's third quarter is not
 * comparable to its first — and a quarter-on-quarter line invites the reader to
 * read a seasonal trough as a decline. Putting the same quarter of each year in
 * one column makes the comparison that means something the easy one to make.
 *
 * DOM rather than a canvas heatmap: the cells carry their own figures, and text
 * inside a canvas cell cannot be selected, searched or reflowed.
 */
export default function SeasonalGrid({
  payload,
  basis,
  field,
}: {
  payload: BistFinancials;
  basis: Basis;
  field: string;
}) {
  const rows = seasonalGrid(payload, basis, field);
  const values = rows.flatMap((row) => row.cells);
  const unit = unitFor(values);
  const measured = values.filter((value): value is number => value != null);
  const ceiling = Math.max(...measured, 0);
  const floor = Math.min(...measured, 0);
  const span = ceiling - floor || 1;

  return (
    <div className="space-y-2 px-1 py-1">
      <p className="text-2xs text-fg-subtle">
        {FIELD_LABELS[field] ?? field}, {unit.label}. Aynı çeyrek aynı sütunda.
      </p>
      <table className="w-full border-separate border-spacing-1 text-2xs">
        <thead>
          <tr>
            <th className="label w-10 text-left font-normal" scope="col">
              Yıl
            </th>
            {['Q1', 'Q2', 'Q3', 'Q4'].map((label) => (
              <th key={label} className="label font-normal" scope="col">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.year}>
              <th className="label text-left font-normal" scope="row">
                {row.year}
              </th>
              {row.cells.map((cell, index) => (
                <td
                  key={index}
                  className="tabnum rounded px-1 py-1.5 text-center"
                  style={
                    cell == null
                      ? undefined
                      : {
                          // A sequential ramp, because the quantity is unsigned
                          // scale rather than a direction. Signed colour on this
                          // grid would read as up-and-down against last quarter,
                          // which is exactly the comparison it exists to avoid.
                          background: `color-mix(in srgb, var(--heat-seq-4) ${
                            10 + ((cell - floor) / span) * 65
                          }%, transparent)`,
                        }
                  }
                >
                  {cell == null ? (
                    <span className="text-fg-subtle">{EMPTY}</span>
                  ) : (
                    (cell / unit.divisor).toFixed(1)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
