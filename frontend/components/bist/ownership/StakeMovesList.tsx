'use client';

import Link from 'next/link';

import type { BistStakeMove } from '@/lib/bist-api';
import { formatDate, formatPercent } from '@/lib/bist-format';
import { STAKE_MOVE_LABEL, formatStakeDelta } from '@/lib/bist-ownership';

interface StakeMovesListProps {
  moves: BistStakeMove[];
  /** The oldest snapshot day, so the empty state can say what "no change" covers. */
  trackingSince: string | null;
  /** Show the holder column — on a company page; hidden on a holder's own page. */
  showHolder?: boolean;
  /** Show the company column — on a holder's page; hidden on a company page. */
  showCompany?: boolean;
  limit?: number;
}

function kindClass(kind: BistStakeMove['kind']): string {
  if (kind === 'new' || kind === 'add') return 'border-up/60 text-up';
  return 'border-down/60 text-down';
}

/**
 * Entries, exits and resizes read off the daily shareholder snapshots.
 *
 * The date shown is the day the change was *observed* on İş Yatırım's card,
 * and the list says so. The card lags the filing, so the KAP list beside this
 * one is usually the earlier witness; this one is the one that carries the
 * numbers.
 */
export default function StakeMovesList({
  moves,
  trackingSince,
  showHolder = true,
  showCompany = true,
  limit,
}: StakeMovesListProps) {
  const rows = limit ? moves.slice(0, limit) : moves;

  if (rows.length === 0) {
    return (
      <p className="px-3 py-4 text-sm text-fg-subtle">
        {trackingSince
          ? `${formatDate(trackingSince)} tarihinden bu yana pay tablosunda değişiklik gözlenmedi. Daha eski giriş ve çıkışlar kayıt altında değil.`
          : 'Pay tablosu henüz günlük olarak kaydedilmedi; giriş ve çıkışlar ikinci kayıttan itibaren görünür.'}
      </p>
    );
  }

  return (
    <ul>
      {rows.map((move) => (
        <li
          key={move.id}
          className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line px-3 py-2 text-sm last:border-0"
        >
          <span className="flex min-w-0 items-center gap-2">
            <span className={`rounded border px-1 py-px text-2xs ${kindClass(move.kind)}`}>
              {STAKE_MOVE_LABEL[move.kind]}
            </span>
            {showHolder && (
              <span className="truncate text-fg">
                {move.entity_id ? (
                  <Link
                    href={`/bist/ortaklik?entity=${encodeURIComponent(move.entity_id)}`}
                    className="hover:underline"
                  >
                    {move.holder}
                  </Link>
                ) : (
                  move.holder
                )}
              </span>
            )}
            {showCompany && (
              <Link
                href={`/bist/hisseler/${move.ticker}`}
                className="truncate text-fg-muted hover:underline"
              >
                {move.ticker}
              </Link>
            )}
          </span>
          <span className="tabnum flex shrink-0 items-center gap-3 text-fg-muted">
            <span title="Önceki → yeni sermaye payı">
              {formatPercent(move.stake_before)} → {formatPercent(move.stake_after)}
            </span>
            {move.delta_pct !== null && (
              <span className={move.delta_pct >= 0 ? 'text-up' : 'text-down'}>
                {formatStakeDelta(move.delta_pct)}
              </span>
            )}
            <span
              className="text-2xs text-fg-subtle"
              title="Kartta gözlendiği gün; bildirim tarihi değil"
            >
              {formatDate(move.observed_at)}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}
