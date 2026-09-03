'use client';

import { useMemo, useState } from 'react';

import Modal from '@/components/ui/Modal';
import { useBistFunds, useBistOverview, useBistStocks } from '@/hooks/useBist';
import { formatSignedPercent } from '@/lib/bist-format';
import {
  searchInstruments,
  slotKey,
  type BistBriefSlot,
  type BistInstrument,
} from '@/lib/bist-brief';

/**
 * Choose what goes in one brief slot.
 *
 * Both boards, one list. A reader following Borsa İstanbul does not think of
 * "shares" and "funds" as two searches — they think of the thing they own — so
 * the split is a label on the row rather than a tab above it.
 *
 * Everything is fetched whole and filtered here, which is the convention the
 * screener pages already set: search is per-keystroke and 623 shares fit in
 * memory comfortably, while a request per character would not. Both queries are
 * gated on `isOpen`, so a picker nobody opens costs nothing, and the funds query
 * uses the same key as `/bist/fonlar` so a reader arriving from there pays for
 * it once.
 */

const KIND_LABEL: Record<BistBriefSlot['kind'], string> = {
  stock: 'Hisse',
  fund: 'Fon',
};

export default function BistBriefPicker({
  isOpen,
  current,
  taken,
  onClose,
  onPick,
  onRemove,
}: {
  isOpen: boolean;
  /** What the slot currently holds, so it can be named in the remove line. */
  current: BistBriefSlot | null;
  /** The other slots — offering one of them would make a duplicate. */
  taken: BistBriefSlot[];
  onClose: () => void;
  onPick: (slot: BistBriefSlot) => void;
  /** Absent for the "add a slot" flow, where there is nothing to remove. */
  onRemove?: () => void;
}) {
  const [query, setQuery] = useState('');

  const stocks = useBistStocks({ sort_by: 'market_cap', limit: 1000 }, isOpen);
  const funds = useBistFunds({ fund_type: 'YAT', sort_by: '1y', limit: 2000 }, isOpen);
  // Already in this page's cache — it is what the board behind the modal drew.
  const overview = useBistOverview(isOpen);

  const isLoading = stocks.isLoading || funds.isLoading;

  const options = useMemo<BistInstrument[]>(() => {
    const held = new Set(taken.map(slotKey));

    const fromStocks: BistInstrument[] = (stocks.data?.stocks ?? []).map((row) => ({
      kind: 'stock' as const,
      code: row.ticker,
      name: row.name,
      note: row.sector,
    }));

    const fromFunds: BistInstrument[] = (funds.data?.funds ?? []).map((row) => ({
      kind: 'fund' as const,
      code: row.code,
      name: row.title,
      note: row.umbrella,
    }));

    return [...fromStocks, ...fromFunds].filter(
      (option) => !held.has(`${option.kind}:${option.code}`)
    );
  }, [stocks.data, funds.data, taken]);

  /**
   * What to offer before anything is typed.
   *
   * The most-traded names and the year's top funds rather than the head of a
   * capitalisation ranking: an empty picker should suggest what is worth
   * looking at today, not the same six giants every time.
   */
  const initial = useMemo<BistInstrument[]>(() => {
    if (query.trim()) return [];
    const held = new Set(taken.map(slotKey));
    const traded: BistInstrument[] = (overview.data?.most_traded ?? []).slice(0, 6).map((row) => ({
      kind: 'stock' as const,
      code: row.ticker,
      name: row.name,
      note: row.sector,
    }));
    const topFunds: BistInstrument[] = (funds.data?.funds ?? []).slice(0, 4).map((row) => ({
      kind: 'fund' as const,
      code: row.code,
      name: row.title,
      note: formatSignedPercent(row.framed_returns?.['1y']?.nominal ?? null) + ' · 1 yıl',
    }));
    return [...traded, ...topFunds].filter((option) => !held.has(`${option.kind}:${option.code}`));
  }, [query, overview.data, funds.data, taken]);

  const suggestions = query.trim() ? searchInstruments(options, query, 14) : initial;

  const submit = (option: BistInstrument) => {
    onPick({ kind: option.kind, code: option.code });
    setQuery('');
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Enstrüman seç" maxWidth="max-w-md">
      <div className="p-4">
        <label htmlFor="bist-brief-search" className="label">
          Hisse veya fon
        </label>
        <input
          id="bist-brief-search"
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="THYAO, İş Portföy, DFI…"
          className="mt-1.5 w-full rounded border border-line bg-surface-2 px-2.5 py-1.5 text-sm text-fg placeholder:text-fg-subtle focus:border-line-strong focus:outline-none"
        />
        <p className="mt-1.5 text-2xs text-fg-subtle">
          Borsa İstanbul hisseleri ve TEFAS fonları birlikte aranır.
        </p>

        <div className="mt-4">
          <span className="label">
            {query.trim() ? 'Eşleşenler' : 'Bugün en çok işlem görenler ve yılın fonları'}
          </span>
          <div className="custom-scrollbar mt-1.5 max-h-72 overflow-y-auto overflow-x-hidden">
            {isLoading && suggestions.length === 0 ? (
              <div className="shimmer h-16 rounded" aria-hidden />
            ) : suggestions.length ? (
              <ul className="divide-y divide-line">
                {suggestions.map((option) => (
                  <li key={`${option.kind}:${option.code}`}>
                    <button
                      type="button"
                      onClick={() => submit(option)}
                      className="flex w-full items-center gap-2.5 px-1 py-2 text-left transition-colors hover:bg-surface-2"
                    >
                      <span
                        className={`label shrink-0 rounded px-1.5 py-0.5 ${
                          option.kind === 'stock'
                            ? 'bg-accent-bg text-accent-soft'
                            : 'bg-surface-2 text-fg-muted'
                        }`}
                      >
                        {KIND_LABEL[option.kind]}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-fg">{option.code}</span>
                        <span className="block truncate text-2xs text-fg-subtle">
                          {option.name}
                        </span>
                      </span>
                      {option.note && (
                        <span className="shrink-0 truncate text-2xs text-fg-subtle">
                          {option.note}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              // Nothing matched, which is not the same as nothing being loaded.
              // The code has to exist on one of the two boards — unlike the
              // crypto picker there is no resolver behind this to try a guess
              // against, so the honest answer is that it is not listed.
              <p className="py-3 text-2xs text-fg-subtle">
                “{query}” için Borsa İstanbul veya TEFAS listelerinde eşleşme yok.
              </p>
            )}
          </div>
        </div>

        {onRemove && current && (
          <div className="mt-4 border-t border-line pt-3">
            <button
              type="button"
              onClick={() => {
                onRemove();
                onClose();
              }}
              className="text-2xs text-fg-subtle transition-colors hover:text-down"
            >
              {current.code} kartını kaldır
            </button>
          </div>
        )}
      </div>
    </Modal>
  );
}
