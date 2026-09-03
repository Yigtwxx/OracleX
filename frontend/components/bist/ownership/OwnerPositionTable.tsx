'use client';

import Link from 'next/link';

import type { BistOwnershipPosition } from '@/lib/bist-api';
import { formatCompactTry, formatPercent } from '@/lib/bist-format';
import { VALUE_BASIS_LABEL, formatStakeDelta, sinceLabel } from '@/lib/bist-ownership';

interface OwnerPositionTableProps {
  positions: BistOwnershipPosition[];
}

/**
 * Every stake one holder has, largest value first.
 *
 * Two percentages per row and they mean different things: `stake` is the
 * share of the *company*, `weight` is the share of the *holder's* known
 * value. The column headers spell both out because a reader who confuses
 * them reads a 91% stake in Halkbank as Halkbank being 91% of the fund.
 *
 * The basis chip is on every row rather than in a footnote: one table can
 * mix stakes marked at market cap with fund positions the filing valued, and
 * the difference belongs beside the number.
 *
 * "Değişim" and "Giriş" come from the daily snapshots and are exactly as
 * old as those: a dash is "no second snapshot yet", `0` is "unchanged", and
 * `≤ date` is "already there when recording began" — never an entry date.
 */
export default function OwnerPositionTable({ positions }: OwnerPositionTableProps) {
  if (positions.length === 0) {
    return (
      <p className="px-3 py-4 text-sm text-fg-subtle">
        XU100 kartlarında bu ortağın %5 üzeri bir payı yok.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-line">
            <th className="label px-3 py-2 text-left">Şirket</th>
            <th className="label px-3 py-2 text-right" title="Şirket sermayesindeki pay">
              Sermaye payı
            </th>
            <th
              className="label px-3 py-2 text-right"
              title="Bir önceki günlük kayda göre, sermaye puanı"
            >
              Değişim
            </th>
            <th
              className="label px-3 py-2 text-right"
              title="Pay tablosunda ilk görüldüğü gün; ≤ ise kayıt başlangıcında zaten vardı"
            >
              Giriş
            </th>
            <th className="label px-3 py-2 text-right">Değer</th>
            <th
              className="label px-3 py-2 text-right"
              title="Ortağın değerlenen toplamı içindeki pay"
            >
              Ağırlık
            </th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.ticker} className="border-b border-line last:border-0">
              <td className="px-3 py-2">
                <Link
                  href={`/bist/hisseler/${position.ticker}`}
                  className="text-fg transition-colors hover:underline"
                >
                  <span className="font-medium">{position.ticker}</span>
                  <span className="ml-1.5 text-fg-muted">{position.name}</span>
                </Link>
                {position.note && (
                  <span className="ml-1.5 text-2xs text-warn" title={position.note}>
                    ⚑
                  </span>
                )}
              </td>
              <td className="tabnum px-3 py-2 text-right text-fg">
                {formatPercent(position.stake_pct)}
              </td>
              <td
                className={`tabnum px-3 py-2 text-right ${
                  position.delta_pct === null || Math.abs(position.delta_pct) < 0.0001
                    ? 'text-fg-subtle'
                    : position.delta_pct > 0
                      ? 'text-up'
                      : 'text-down'
                }`}
                title={
                  position.previous_stake_pct === null
                    ? 'Karşılaştırılacak ikinci kayıt yok'
                    : `Önceki kayıt: ${formatPercent(position.previous_stake_pct)}`
                }
              >
                {formatStakeDelta(position.delta_pct)}
              </td>
              <td className="tabnum px-3 py-2 text-right text-fg-muted">
                {sinceLabel(position.since, position.at_baseline)}
              </td>
              <td className="tabnum px-3 py-2 text-right">
                <span className="text-fg">
                  {position.value_try === null ? '—' : formatCompactTry(position.value_try)}
                </span>
                <span className="ml-1.5 text-2xs text-fg-subtle">
                  {VALUE_BASIS_LABEL[position.value_basis]}
                </span>
              </td>
              <td className="px-3 py-2 text-right">
                {position.weight_pct === null ? (
                  <span className="text-fg-subtle">—</span>
                ) : (
                  <span className="flex items-center justify-end gap-2">
                    <span className="relative h-1 w-14 overflow-hidden rounded-full bg-surface-2">
                      <span
                        className="absolute left-0 top-0 h-full rounded-full"
                        style={{
                          width: `${Math.min(100, position.weight_pct * 100)}%`,
                          minWidth: 2,
                          background: 'var(--nav-bist-ownership)',
                        }}
                      />
                    </span>
                    <span className="tabnum w-12 text-fg-muted">
                      {formatPercent(position.weight_pct)}
                    </span>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
