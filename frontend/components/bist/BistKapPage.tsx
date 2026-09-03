'use client';

import { AlertTriangle, Clock, ExternalLink, RefreshCw, Search, Sparkles, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import AiNote from '@/components/ui/AiNote';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup from '@/components/ui/ToggleGroup';
import { useBistKap, useBistKapNote } from '@/hooks/useBist';
import type { BistDisclosure } from '@/lib/bist-api';
import {
  BAND_CHIP,
  BAND_FILL,
  BAND_LEVEL_LABEL,
  BAND_TITLE,
  kapNoteMessage,
  kapNoteRetryable,
  scoreFillPct,
} from '@/lib/bist-kap';
import { formatDateTime, formatRelative } from '@/lib/bist-format';
import BistPageShell from './BistPageShell';

/**
 * The category filter.
 *
 * `FON` is behind "Tümü" rather than being a button of its own because it is
 * roughly nine filings in ten — a portfolio manager reporting an overnight
 * repo, forty of them stamped the same minute. Promoting it to a tab would
 * invite a reader to select the noise.
 */
const CATEGORY_FILTERS = [
  { value: '', label: 'Önemli' },
  { value: 'ODA', label: 'Özel durum' },
  { value: 'FR', label: 'Finansal rapor' },
  { value: 'all', label: 'Tümü' },
] as const;

type CategoryFilter = (typeof CATEGORY_FILTERS)[number]['value'];

/** Long enough to swallow a typed ticker, short enough not to feel held. */
const TICKER_DEBOUNCE_MS = 300;

/**
 * How consequential this filing's class is, as three segments.
 *
 * The chip beside it names the *class*; this ranks it. Both are needed because
 * neither answers the other's question: "Sermaye artırımı" means nothing to a
 * reader who does not follow Turkish corporate filings, and a lit bar means
 * nothing without the noun that earned it.
 *
 * `role="img"` with a written label rather than three coloured divs left bare.
 * The bar is the only thing on the row that ranks anything, and rank encoded
 * purely as colour and length is rank a screen reader never receives.
 */
function MaterialityBar({ item }: { item: BistDisclosure }) {
  const width = scoreFillPct(item.score);

  return (
    <span
      role="img"
      aria-label={BAND_LEVEL_LABEL[item.band]}
      title={BAND_TITLE[item.band]}
      className={`h-1.5 w-20 shrink-0 overflow-hidden rounded-full ${
        // Dashed and unfilled, so an unread filing cannot be mistaken for one
        // that was read and came back low. It is the only "absent" vocabulary
        // this board has, and the row it appears on is the row the analysis
        // button exists for.
        width === 0 ? 'border border-dashed border-line' : 'bg-line'
      }`}
    >
      {width > 0 && (
        <span
          aria-hidden="true"
          className={`block h-full rounded-full ${BAND_FILL[item.band]}`}
          style={{ width: `${width}%` }}
        />
      )}
    </span>
  );
}

/**
 * What kind of filing this is, on every row of the tape.
 *
 * Computed in Python from the form KAP filed it on — see
 * `services/bist/kap_materiality.py` — which is what makes it affordable on all
 * sixty rows at once. The model is not consulted here and never sees a row it
 * was not asked about; it explains this classification inside the note below,
 * and is forbidden from overturning it.
 *
 * The `title` is not decoration. A three-level band beside a company
 * announcement is the kind of thing a reader will take for a call on the price,
 * and it is not one — the tooltip is where that is said in as many words.
 */
function BandChip({ item }: { item: BistDisclosure }) {
  return (
    <span
      title={BAND_TITLE[item.band]}
      className={`shrink-0 rounded border px-1 py-px font-medium ${BAND_CHIP[item.band]}`}
    >
      {item.event_label}
    </span>
  );
}

/**
 * The model's read of one filing, under the row it belongs to.
 *
 * Inline rather than in a drawer or a modal. A filing is read against the ones
 * around it — three notifications from the same company in an hour is the
 * story on some afternoons — and a panel that covers the tape hides exactly the
 * context the note is being read for.
 *
 * Mounted only while the row is open, which is what makes the request
 * on-demand: the hook fires on mount, and the tape does not ask a local model
 * for sixty paragraphs nobody requested.
 */
function KapNote({ index }: { index: number }) {
  const { data, isError, refetch, isFetching } = useBistKapNote(index);
  const message = kapNoteMessage(data?.note, isError);

  return (
    // 5.5rem is the row's own title column — 12px of padding, the 64px ticker
    // slot and the 12px gap — so the note begins under the headline it explains
    // rather than under the ticker beside it.
    <div className="border-t border-line bg-surface-2/40 px-3 py-2.5 sm:pl-[5.5rem]">
      <p className="label mb-1.5 flex items-center gap-1.5">
        <Sparkles className="h-3 w-3" aria-hidden="true" />
        AI analizi
      </p>

      {/* `aria-live` because the note lands seconds after the press, long after
          focus has moved on — without it a screen reader is never told the
          thing the button was pressed for has arrived. */}
      <div aria-live="polite">
        {message ? (
          <p className="text-xs leading-relaxed text-fg-subtle">{message}</p>
        ) : (
          <AiNote aiNote={data?.note} />
        )}
      </div>

      {kapNoteRetryable(data?.note, isError) && (
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="mt-1.5 rounded-md border border-line px-2 py-0.5 text-2xs text-fg-muted transition-colors hover:border-line-strong hover:text-fg disabled:opacity-50"
        >
          Tekrar dene
        </button>
      )}
    </div>
  );
}

export default function BistKapPage() {
  const [category, setCategory] = useState<CategoryFilter>('');
  const [ticker, setTicker] = useState('');
  const [settledTicker, setSettledTicker] = useState('');
  // One open note at a time. Each one is a run of a local model, and a tape
  // whose rows all stayed open would queue sixty of them behind the reader.
  const [openNote, setOpenNote] = useState<number | null>(null);

  // The ticker filter is applied on the server, unlike the screener's search
  // next door, because it runs over the whole six-hundred-row buffer rather
  // than the sixty rows on screen — a code whose last filing was yesterday has
  // to stay findable. That makes it one request and one fresh query key per
  // keystroke unless it is held: typing THYAO fired five.
  useEffect(() => {
    const timer = setTimeout(
      () => setSettledTicker(ticker.trim().toUpperCase()),
      TICKER_DEBOUNCE_MS
    );
    return () => clearTimeout(timer);
  }, [ticker]);

  const { data, isLoading, isError, isFetching, refetch } = useBistKap({
    limit: 60,
    ticker: settledTicker || undefined,
    categories: category || undefined,
  });

  const showColdError = isError && !data;

  return (
    <BistPageShell
      title="KAP"
      description="Kamuyu Aydınlatma Platformu bildirim akışı."
      action={
        <button
          type="button"
          onClick={() => refetch()}
          aria-label="Yenile"
          className="rounded-md p-1 text-fg-subtle transition-colors hover:text-fg"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
        </button>
      }
    >
      <div className="surface surface-flat flex min-h-0 flex-col overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-2">
          <ToggleGroup
            label="Bildirim türü"
            options={CATEGORY_FILTERS.map((option) => ({ ...option }))}
            value={category}
            onChange={setCategory}
          />
          <div role="search" className="ml-auto flex items-center gap-1.5">
            <Search className="h-3.5 w-3.5 text-fg-subtle" aria-hidden="true" />
            <input
              value={ticker}
              onChange={(event) => setTicker(event.target.value)}
              onKeyDown={(event) => event.key === 'Escape' && setTicker('')}
              placeholder="Hisse kodu"
              aria-label="Hisse koduna göre filtrele"
              className="w-32 bg-transparent text-sm uppercase text-fg outline-none placeholder:normal-case placeholder:text-fg-subtle"
            />
            {ticker && (
              <button
                type="button"
                onClick={() => setTicker('')}
                aria-label="Filtreyi temizle"
                className="text-fg-subtle transition-colors hover:text-fg"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <span className="label shrink-0">{data?.count ?? 0} bildirim</span>
        </div>

        {/*
          A throttled tape and a quiet session look identical from the rows
          alone — both are a short list — so the one case a reader would
          misread is named rather than left to inference.
        */}
        {data?.rate_limited && (
          <div className="flex items-start gap-2 border-b border-line bg-warn/5 px-3 py-2 text-2xs text-warn">
            <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
            <span>
              KAP şu anda istek sınırı uyguluyor. Akış elde tutulan bildirimlerden geliyor ve sınır
              kalkana kadar yeni bildirimlerle güncellenmiyor.
            </span>
          </div>
        )}

        {showColdError ? (
          <StatusMessage
            icon={AlertTriangle}
            action={
              <button
                type="button"
                onClick={() => refetch()}
                className="rounded-md border border-line px-3 py-1 text-sm text-fg transition-colors hover:border-line-strong"
              >
                Tekrar dene
              </button>
            }
          >
            KAP akışı şu anda alınamıyor. Platform kısa süreli istek sınırı uygulamış olabilir.
          </StatusMessage>
        ) : isLoading && !data ? (
          <StatusMessage icon={RefreshCw}>Bildirimler yükleniyor…</StatusMessage>
        ) : (data?.disclosures.length ?? 0) === 0 ? (
          <StatusMessage icon={Clock}>
            {ticker ? `${ticker} için bildirim bulunamadı.` : 'Bu filtreyle bildirim yok.'}
          </StatusMessage>
        ) : (
          <ul className="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
            {data?.disclosures.map((item) => {
              const isOpen = openNote === item.index;
              return (
                <li key={item.index} className="border-b border-line last:border-0">
                  {/* The analyse button is a sibling of the link, not a child of
                      it: a button inside an anchor is invalid, and browsers
                      resolve it by following the link on every press. */}
                  <div className="flex items-start transition-colors hover:bg-surface-2">
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex min-w-0 flex-1 items-start gap-3 px-3 py-2.5"
                    >
                      <span className="w-16 shrink-0 pt-0.5">
                        {item.ticker ? (
                          <span className="text-sm font-medium text-fg">{item.ticker}</span>
                        ) : (
                          <span className="label">BIST</span>
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm text-fg">{item.title}</span>
                        {item.summary && (
                          <span className="mt-0.5 block truncate text-2xs text-fg-muted">
                            {item.summary}
                          </span>
                        )}
                        <span className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-2xs text-fg-subtle">
                          <MaterialityBar item={item} />
                          <BandChip item={item} />
                          <span className="truncate">
                            {item.company} · {item.category_label}
                          </span>
                          {item.is_late && <span className="text-warn">· gecikmeli</span>}
                        </span>
                      </span>
                      <span
                        className="shrink-0 text-2xs text-fg-subtle"
                        title={formatDateTime(item.published_at)}
                      >
                        {formatRelative(item.published_at)}
                      </span>
                    </a>

                    <button
                      type="button"
                      onClick={() => setOpenNote(isOpen ? null : item.index)}
                      aria-expanded={isOpen}
                      aria-label={`${item.ticker || item.company} bildirimini analiz et`}
                      className={`mt-2 shrink-0 rounded-md border px-2 py-0.5 text-2xs transition-colors ${
                        isOpen
                          ? 'border-line-strong bg-surface-2 text-fg'
                          : 'border-line text-fg-muted hover:border-line-strong hover:text-fg'
                      }`}
                    >
                      Analiz et
                    </button>

                    {/* The icon keeps the far right, which is where it has to
                        be: it is the row's "this opens KAP" affordance, and
                        moving it inboard of a button would make the button look
                        like the thing the row opens.

                        A second anchor to the same URL rather than an inert
                        icon, so it stays clickable — hidden from assistive
                        technology and skipped by the tab order, because the
                        link it duplicates is the whole row beside it. */}
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-hidden="true"
                      tabIndex={-1}
                      className="ml-2 mr-3 mt-2.5 shrink-0 text-fg-subtle transition-colors hover:text-fg"
                    >
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>

                  {isOpen && <KapNote index={item.index} />}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </BistPageShell>
  );
}
