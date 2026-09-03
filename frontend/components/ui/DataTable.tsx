'use client';

import { ChevronDown, ChevronUp, ChevronsUpDown } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';

export type SortDirection = 'asc' | 'desc';

export interface ColumnDef<T> {
  key: string;
  label: string;
  /** A CSS grid track, e.g. `'minmax(140px, 1.4fr)'` or `'90px'`. */
  width: string;
  align?: 'left' | 'right' | 'center';
  /**
   * What to sort this column by.
   *
   * Omitted means the column is not sortable. Returning `null` means this row
   * has no value for it — those sort to the bottom in *both* directions, which
   * is the rule that matters: ascending by price-to-earnings should surface the
   * cheapest company, not the eighty with no earnings and therefore no ratio.
   */
  sortValue?: (row: T) => number | string | null;
  render: (row: T) => ReactNode;
  /** Header tooltip — the place to spell out an abbreviation. */
  title?: string;
}

interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  rows: T[];
  /**
   * A stable key per row.
   *
   * Takes the index as well because a payload's own identifier is not always
   * unique: the VİOP board lists two `USDTRY (30 Eyl 26) Alim opsiyonu` rows at
   * different strikes and prints the strike nowhere in the label, so a key
   * built from the label alone silently collapses them into one.
   */
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  isLoading?: boolean;
  /** Rows per page. Fifty is what the crypto board settled on. */
  pageSize?: number;
  initialSort?: { key: string; direction: SortDirection };
  emptyMessage?: string;
  /**
   * Cap on the rows region before it scrolls vertically.
   *
   * Unset by default: a table nested in its own scroller traps the wheel — the
   * reader scrolls the page, hits the board, and the page stops moving while a
   * second scrollbar takes over. A full page of rows rendered inline and
   * scrolled by the page itself is the behaviour a screener reader expects.
   * Pass a value only where the table shares a viewport with panels that must
   * stay visible.
   */
  bodyMaxHeight?: number | string;
  /** Labels, so the same table serves a Turkish and an English surface. */
  labels?: { page: string; of: string; previous: string; next: string; rows: string };
}

const DEFAULT_LABELS = {
  page: 'Sayfa',
  of: '/',
  previous: 'Önceki',
  next: 'Sonraki',
  rows: 'kayıt',
};

/** Matches the crypto board's page size — see `components/overview/AssetTable.tsx`. */
const DEFAULT_PAGE_SIZE = 50;

/**
 * A sortable, paginated table.
 *
 * The first one in this codebase. Every existing table is a hand-rolled CSS
 * grid with either a fixed order or a single `.sort()` applied before render —
 * fine for a board of twenty rows, unusable for six hundred stocks or a
 * thousand funds where "which of these is cheapest" is the actual question.
 *
 * Structure follows the crypto board rather than inventing one: a single
 * `gridTemplateColumns` string shared by the header, the skeleton and the rows,
 * so the three can never drift out of alignment. It is a grid of `div`s rather
 * than a `<table>` for the same reason that one is — sticky headers and
 * per-column widths are far simpler here — with `role` attributes supplying the
 * semantics a real table would have given for free.
 *
 * Pagination rather than virtualisation. No windowing library is in the
 * dependency tree, six hundred rows of DOM is enough to make Safari's
 * `background-attachment: fixed` rim janky, and a page control is the
 * behaviour a reader of a market screener already expects.
 */
export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  isLoading = false,
  pageSize = DEFAULT_PAGE_SIZE,
  initialSort,
  emptyMessage = 'Kayıt bulunamadı.',
  bodyMaxHeight,
  labels = DEFAULT_LABELS,
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(initialSort?.key ?? null);
  const [direction, setDirection] = useState<SortDirection>(initialSort?.direction ?? 'desc');
  const [page, setPage] = useState(1);

  const gridStyle = useMemo(
    () => ({ gridTemplateColumns: columns.map((column) => column.width).join(' ') }),
    [columns]
  );

  const sorted = useMemo(() => {
    const column = columns.find((candidate) => candidate.key === sortKey);
    if (!column?.sortValue) return rows;
    const read = column.sortValue;

    return [...rows].sort((left, right) => {
      const a = read(left);
      const b = read(right);
      // Missing last in both directions. Mapping null to -Infinity would put
      // unmeasured rows *below* the worst real value rather than outside the
      // ranking, which reads as a measurement.
      if (a === null && b === null) return 0;
      if (a === null) return 1;
      if (b === null) return -1;
      const order =
        typeof a === 'string' || typeof b === 'string'
          ? String(a).localeCompare(String(b), 'tr')
          : (a as number) - (b as number);
      return direction === 'asc' ? order : -order;
    });
  }, [rows, columns, sortKey, direction]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  // Clamped rather than stored: a refetch that returns fewer rows must not
  // strand the reader on a page that no longer exists.
  const currentPage = Math.min(page, totalPages);
  const visible = sorted.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  // Back to the first page whenever the result set changes underneath — a new
  // filter with the reader still on page 7 looks like an empty board.
  useEffect(() => {
    setPage(1);
  }, [rows.length, sortKey, direction]);

  /**
   * Which way a column sorts on its first click.
   *
   * Descending for a number — on a screener the interesting end of every
   * numeric column is the top one. Ascending for text, because descending
   * there means Z→A, and a reader who clicks "Hisse" is looking for the
   * alphabet, not the reverse of it. Read off the data rather than declared
   * per column so a new table cannot forget to say which it is.
   */
  const firstDirection = (column: ColumnDef<T>): SortDirection => {
    const read = column.sortValue;
    if (!read) return 'desc';
    for (const row of rows) {
      const value = read(row);
      if (value !== null) return typeof value === 'string' ? 'asc' : 'desc';
    }
    return 'desc';
  };

  const toggleSort = (column: ColumnDef<T>) => {
    if (!column.sortValue) return;
    if (sortKey === column.key) {
      setDirection((previous) => (previous === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(column.key);
      setDirection(firstDirection(column));
    }
  };

  const ariaSort = (column: ColumnDef<T>): 'ascending' | 'descending' | 'none' | undefined => {
    if (!column.sortValue) return undefined;
    if (sortKey !== column.key) return 'none';
    return direction === 'asc' ? 'ascending' : 'descending';
  };

  const ALIGN_TEXT = { left: 'text-left', right: 'text-right', center: 'text-center' } as const;
  const ALIGN_FLEX = {
    left: 'justify-start',
    right: 'justify-end',
    center: 'justify-center',
  } as const;

  const cellClass = (column: ColumnDef<T>) =>
    `min-w-0 truncate ${ALIGN_TEXT[column.align ?? 'left']}`;

  return (
    <div className="flex min-h-0 flex-col">
      {/* One horizontal scroller around the header *and* the rows, so the two
          can never drift out of alignment.
          
          Without it a phone silently clips the table: eleven columns need
          about 1360px, the viewport gives 356, and the document reports no
          overflow because the surface hides it — the reader simply cannot
          reach the multiples. This is the rule `components/ui/Panel.tsx`
          already states: a child that genuinely needs the width declares its
          own `overflow-x` and scrolls inside itself. */}
      <div className="custom-scrollbar min-h-0 flex-1 overflow-x-auto">
        {/* A floor, not `min-w-max`.
        
            `max-content` would force the natural sum of every column and make a
            1440px desktop scroll sideways too, throwing away the `minmax()`
            flexibility the column definitions already carry. A fixed floor lets
            wide screens compress the flexible columns as before and only starts
            scrolling once there is genuinely not enough room to read them. */}
        <div className="min-w-[1180px]">
          {/* Header. Outside the vertical scroll container so an overlay scrollbar
          never paints over it — same reason Panel lifts its column row out. */}
          <div
            role="row"
            style={gridStyle}
            className="grid shrink-0 items-center gap-3 border-b border-line px-3 py-2"
          >
            {columns.map((column) => {
              const sortable = !!column.sortValue;
              const active = sortKey === column.key;
              // The arrow points at the end of the column the big values are
              // now sitting at: up when the largest is on top (descending),
              // down when it is at the bottom (ascending). The opposite
              // mapping — down for descending, as a spreadsheet draws it —
              // read backwards to everyone who used this board, because on a
              // screener the eye is on where the extreme *is*, not on which
              // way the values run. `aria-sort` still reports the real
              // direction, so the semantics do not follow the glyph.
              const Icon = !active ? ChevronsUpDown : direction === 'asc' ? ChevronDown : ChevronUp;
              return (
                <div key={column.key} role="columnheader" aria-sort={ariaSort(column)}>
                  {sortable ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column)}
                      title={column.title}
                      className={`label flex w-full items-center gap-1 transition-colors hover:text-fg ${
                        ALIGN_FLEX[column.align ?? 'left']
                      } ${active ? 'text-fg' : ''}`}
                    >
                      <span className="truncate">{column.label}</span>
                      <Icon
                        className={`h-3 w-3 shrink-0 ${active ? 'text-accent' : 'text-fg-subtle'}`}
                        aria-hidden="true"
                      />
                    </button>
                  ) : (
                    <span
                      title={column.title}
                      className={`label block truncate ${ALIGN_TEXT[column.align ?? 'left']}`}
                    >
                      {column.label}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          <div
            className={bodyMaxHeight === undefined ? undefined : 'custom-scrollbar overflow-y-auto'}
            style={bodyMaxHeight === undefined ? undefined : { maxHeight: bodyMaxHeight }}
          >
            {isLoading && rows.length === 0 ? (
              Array.from({ length: 12 }).map((_, index) => (
                <div
                  key={index}
                  style={gridStyle}
                  className="grid items-center gap-3 border-b border-line px-3 py-2"
                >
                  {columns.map((column) => (
                    <div key={column.key} className="shimmer h-3 rounded" />
                  ))}
                </div>
              ))
            ) : visible.length === 0 ? (
              <p className="px-3 py-10 text-center text-sm text-fg-muted">{emptyMessage}</p>
            ) : (
              visible.map((row, index) => (
                <div
                  key={rowKey(row, index)}
                  role={onRowClick ? 'button' : 'row'}
                  tabIndex={onRowClick ? 0 : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            onRowClick(row);
                          }
                        }
                      : undefined
                  }
                  style={gridStyle}
                  className={`grid items-center gap-3 border-b border-line px-3 py-2 text-sm ${
                    onRowClick
                      ? 'cursor-pointer transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none'
                      : ''
                  }`}
                >
                  {columns.map((column) => (
                    <div key={column.key} className={cellClass(column)}>
                      {column.render(row)}
                    </div>
                  ))}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {totalPages > 1 && (
        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-line px-3 py-2 text-xs text-fg-muted">
          <span className="tabnum">
            {sorted.length} {labels.rows}
          </span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setPage(currentPage - 1)}
              disabled={currentPage <= 1}
              className="rounded px-2 py-0.5 transition-colors hover:text-fg disabled:opacity-40 disabled:hover:text-fg-muted"
            >
              {labels.previous}
            </button>
            <span className="tabnum">
              {labels.page} {currentPage} {labels.of} {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="rounded px-2 py-0.5 transition-colors hover:text-fg disabled:opacity-40 disabled:hover:text-fg-muted"
            >
              {labels.next}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
