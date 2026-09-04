'use client';

import { Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';

import { useBistStocks } from '@/hooks/useBist';
import { type BistInstrument, searchInstruments } from '@/lib/bist-brief';

/**
 * Which company the board is showing.
 *
 * `BistBriefPicker` is next door and was not reused: it is a modal for filling
 * one of several comparison slots, so its props carry `taken`, `onRemove` and
 * an open/closed state that mean nothing here. Its search *is* reused —
 * `searchInstruments` is the realm's tested ranking primitive and folds Turkish
 * case, so "sise" finds ŞİŞE.
 */
export default function TickerPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (ticker: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const { data } = useBistStocks({ sort_by: 'market_cap', limit: 1000 });

  const options = useMemo<BistInstrument[]>(
    () =>
      (data?.stocks ?? []).map((stock) => ({
        kind: 'stock' as const,
        code: stock.ticker,
        name: stock.name,
        note: stock.sector,
      })),
    [data]
  );

  const matches = useMemo(() => searchInstruments(options, query, 8), [options, query]);

  const pick = (code: string) => {
    onChange(code);
    setQuery('');
    setOpen(false);
  };

  return (
    <div className="relative w-full sm:w-72">
      <div
        role="search"
        className="flex items-center gap-1.5 rounded border border-line bg-surface-2 px-2 py-1.5"
      >
        <Search className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
        <input
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              setQuery('');
              setOpen(false);
            }
            if (event.key === 'Enter' && matches[0]) pick(matches[0].code);
          }}
          placeholder={value || 'THYAO, Akbank, EREGL…'}
          aria-label="Şirket ara"
          className="w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery('')}
            aria-label="Aramayı temizle"
            className="text-fg-subtle transition-colors hover:text-fg"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {open && matches.length > 0 && (
        <ul className="custom-scrollbar absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded border border-line bg-surface shadow-lg">
          {matches.map((option) => (
            <li key={option.code}>
              {/* onMouseDown, not onClick: the input's blur fires first and
                  would unmount the list before a click could land. */}
              <button
                type="button"
                onMouseDown={() => pick(option.code)}
                className="flex w-full items-baseline gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-surface-2"
              >
                <span className="w-16 shrink-0 text-sm font-medium text-fg">{option.code}</span>
                <span className="min-w-0 flex-1 truncate text-2xs text-fg-muted">
                  {option.name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
