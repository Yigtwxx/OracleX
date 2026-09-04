'use client';

import { AlertTriangle, ChevronDown, ExternalLink, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import BistChartPanel from '@/components/bist/BistChartPanel';
import BistPageShell from '@/components/bist/BistPageShell';
import MetricTile from '@/components/bist/MetricTile';
import IpoCalendar from '@/components/bist/ipo/IpoCalendar';
import IpoDetailPanel from '@/components/bist/ipo/IpoDetailPanel';
import IpoNote from '@/components/bist/ipo/IpoNote';
import IpoReturnHistogram from '@/components/bist/ipo/IpoReturnHistogram';
import IpoReturnRanking from '@/components/bist/ipo/IpoReturnRanking';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup from '@/components/ui/ToggleGroup';
import { useBistIpos, useBistIposNote } from '@/hooks/useBist';
import type { Ipo } from '@/lib/bist-api';
import {
  EMPTY,
  formatPercent,
  formatRelative,
  formatSignedPercent,
  toneClass,
} from '@/lib/bist-format';
import {
  type IpoBasis,
  type IpoWindow,
  histogramReady,
  ipoStateLabel,
  medianReturn,
  MIN_SAMPLE,
  positiveShare,
  rankByReturn,
  WINDOW_OPTIONS,
} from '@/lib/bist-ipo';

/** `0` means "everything the calendar carries"; the API's ceiling is 120 months. */
const ALL_MONTHS = 120;

type StateFilter = 'all' | 'upcoming' | 'listed';

export default function BistIpoPage() {
  const [window, setWindow] = useState<IpoWindow>(24);
  const [requested, setRequested] = useState<IpoBasis>('real');
  const [stateFilter, setStateFilter] = useState<StateFilter>('all');
  const [openRow, setOpenRow] = useState<string | null>(null);

  const monthsBack = window === 0 ? ALL_MONTHS : window;
  const { data, isLoading, isError, isFetching, refetch } = useBistIpos(monthsBack);
  const note = useBistIposNote(monthsBack);

  // The board has its own frame switch, and the same rule applies as on the
  // Bilanço page: without an inflation series nothing may be labelled real.
  const deflatable = Boolean(data?.inflation.available);
  const basis: IpoBasis = deflatable ? requested : 'nominal';

  const past = data?.past ?? [];
  const upcoming = data?.upcoming ?? [];
  const ranked = rankByReturn(past, basis);

  return (
    <BistPageShell
      title="Halka Arz"
      description="Borsa İstanbul halka arz takvimi ve arz sonrası getiriler."
      delayed
      action={
        <div className="flex items-center gap-2">
          {data?.source_updated_at && (
            <span
              className="text-2xs text-fg-subtle"
              title="halkarz.com'un kendi güncelleme damgası — bizim çekme zamanımız değil."
            >
              Kaynak {formatRelative(data.source_updated_at)}
            </span>
          )}
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Yenile"
            className="rounded-md p-1 text-fg-subtle transition-colors hover:text-fg"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          </button>
        </div>
      }
    >
      {isError && !data ? (
        <div className="surface">
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
            Halka arz takvimine şu anda ulaşılamıyor. Kaynak site yanıt vermiyor olabilir.
          </StatusMessage>
        </div>
      ) : isLoading && !data ? (
        <div className="surface">
          <StatusMessage icon={RefreshCw}>Takvim yükleniyor…</StatusMessage>
        </div>
      ) : data ? (
        <>
          <IpoNote board={data} basis={basis} note={note.data?.note} isLoading={note.isLoading} />

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <MetricTile label="Yaklaşan arz" value={upcoming.length} note="ilan edilmiş" />
            <MetricTile
              label="Pencerede listelenen"
              value={past.length}
              note={`son ${window === 0 ? 'tüm' : window} ay`}
            />
            <MetricTile
              label={`Medyan getiri`}
              value={formatSignedPercent(medianReturn(past, basis), 0)}
              note={basis === 'real' ? 'reel' : 'nominal'}
              tone={toneClass(medianReturn(past, basis))}
              title="Arz fiyatına göre, kesinleşen fiyat üzerinden."
            />
            <MetricTile
              label="Pozitif getiri oranı"
              value={formatPercent(positiveShare(past, basis), 0)}
              note={basis === 'real' ? 'reel' : 'nominal'}
            />
            <MetricTile
              label="Ölçülebilen"
              value={`${data.coverage.returns_measured} / ${past.length}`}
              note="getirisi hesaplanan"
              title="Ölçülemeyenler grafiklerin ve medyanın dışında."
            />
            <MetricTile
              label="Tarihi belli değil"
              value={data.coverage.undated}
              note="takvimde tarihi yok"
            />
          </div>

          <div className="surface surface-flat flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2">
            <ToggleGroup
              label="Pencere"
              options={WINDOW_OPTIONS.map((option) => ({
                value: String(option.value),
                label: option.label,
              }))}
              value={String(window)}
              onChange={(next) => setWindow(Number(next) as IpoWindow)}
            />
            {deflatable ? (
              <ToggleGroup
                label="Getiri çerçevesi"
                options={[
                  { value: 'real', label: 'Reel' },
                  { value: 'nominal', label: 'Nominal' },
                ]}
                value={requested}
                onChange={(next) => setRequested(next as IpoBasis)}
              />
            ) : (
              <span className="flex items-center gap-1.5 text-2xs text-warn">
                <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                Enflasyon serisi yok; getiriler yalnızca nominal.
              </span>
            )}
            <ToggleGroup
              label="Durum"
              options={[
                { value: 'all', label: 'Tümü' },
                { value: 'upcoming', label: 'Yaklaşan' },
                { value: 'listed', label: 'Listelenmiş' },
              ]}
              value={stateFilter}
              onChange={(next) => setStateFilter(next as StateFilter)}
            />
          </div>

          <div className="grid gap-2 xl:grid-cols-2">
            <BistChartPanel
              title="Halka arz getirisi"
              legend={`Arz fiyatından bugüne · ${basis === 'real' ? 'reel' : 'nominal'} · ${
                ranked.length
              } ölçüldü, ${past.length - ranked.length} ölçülemedi`}
            >
              {ranked.length > 0 ? (
                <IpoReturnRanking rows={past} basis={basis} />
              ) : (
                <StatusMessage icon={AlertTriangle}>
                  Bu pencerede getirisi ölçülebilen halka arz yok.
                </StatusMessage>
              )}
            </BistChartPanel>

            <BistChartPanel title="Halka arz takvimi" legend="Talep toplama ayına göre">
              <IpoCalendar rows={upcoming} />
            </BistChartPanel>

            <BistChartPanel
              title="Getiri dağılımı"
              legend="Sabit kovalar · pencereler arasında karşılaştırılabilir"
            >
              {histogramReady(past, basis) ? (
                <IpoReturnHistogram rows={past} basis={basis} />
              ) : (
                <StatusMessage icon={AlertTriangle}>
                  {`Bu pencerede ölçülebilen ${ranked.length} halka arz var; dağılım için en az ${MIN_SAMPLE} gerekiyor.`}
                </StatusMessage>
              )}
            </BistChartPanel>

            <BistChartPanel
              title="Kaynak ve kapsam"
              legend="Bu tahtanın neyi görüp neyi göremediği"
            >
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 px-1 py-2 text-2xs">
                {[
                  ['Takvimdeki toplam arz', data.coverage.index_rows],
                  ['Bu pencerede', data.coverage.in_window],
                  ['Okunan detay sayfası', data.coverage.detail_pages_read],
                  ['Okunamayan detay sayfası', data.coverage.detail_pages_failed],
                  ['Getirisi ölçülen', data.coverage.returns_measured],
                  ['Getirisi ölçülemeyen', data.coverage.returns_unmeasured],
                ].map(([label, value]) => (
                  <div key={label as string} className="flex items-baseline justify-between gap-2">
                    <dt className="text-fg-subtle">{label}</dt>
                    <dd className="tabnum text-fg">{value as number}</dd>
                  </div>
                ))}
              </dl>
              <p className="px-1 pb-2 text-2xs leading-relaxed text-fg-subtle">
                Takvim halkarz.com&apos;dan geliyor ve topluluk tarafından tutuluyor. Tahta ilk
                açıldığında detay sayfaları kademeli dolar; okunamayan satırlar yine listelenir,
                eksik alanları işaretlenir.
              </p>
            </BistChartPanel>
          </div>

          <IpoList
            rows={
              stateFilter === 'upcoming'
                ? upcoming
                : stateFilter === 'listed'
                  ? past
                  : [...upcoming, ...past]
            }
            basis={basis}
            openRow={openRow}
            onToggle={(slug) => setOpenRow(openRow === slug ? null : slug)}
          />
        </>
      ) : null}
    </BistPageShell>
  );
}

/** The full list, each row expanding to its three published breakdowns. */
function IpoList({
  rows,
  basis,
  openRow,
  onToggle,
}: {
  rows: Ipo[];
  basis: IpoBasis;
  openRow: string | null;
  onToggle: (slug: string) => void;
}) {
  return (
    <div className="surface surface-flat overflow-hidden">
      <div className="flex items-baseline justify-between border-b border-line px-3 py-2">
        <h2 className="text-sm text-fg">Arzlar</h2>
        <span className="label">{rows.length} kayıt</span>
      </div>
      <ul>
        {rows.map((row) => {
          const isOpen = openRow === row.slug;
          const performance = row.performance;
          const value = performance
            ? basis === 'real'
              ? performance.real
              : performance.nominal
            : null;
          return (
            <li key={row.slug} className="border-b border-line last:border-0">
              <div className="flex items-start transition-colors hover:bg-surface-2">
                <button
                  type="button"
                  onClick={() => onToggle(row.slug)}
                  aria-expanded={isOpen}
                  className="flex min-w-0 flex-1 items-start gap-3 px-3 py-2.5 text-left"
                >
                  <span className="w-16 shrink-0 pt-0.5 text-sm font-medium text-fg">
                    {row.ticker ?? <span className="label">—</span>}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-fg">{row.company}</span>
                    <span className="mt-0.5 flex flex-wrap gap-x-2 text-2xs text-fg-subtle">
                      <span>{ipoStateLabel(row.state)}</span>
                      {row.price && (
                        <span>
                          {row.price.is_band
                            ? `${row.price.low}–${row.price.high} TL`
                            : `${row.price.low} TL`}
                        </span>
                      )}
                      {row.listing_date && <span>ilk işlem {row.listing_date}</span>}
                      {row.unparsed.length > 0 && (
                        <span className="text-warn">
                          {row.unparsed.includes('offer_dates')
                            ? 'tarih belli değil'
                            : 'eksik alan'}
                        </span>
                      )}
                    </span>
                  </span>
                  <span className={`tabnum shrink-0 text-sm ${toneClass(value)}`}>
                    {value != null ? formatSignedPercent(value, 0) : EMPTY}
                  </span>
                  <ChevronDown
                    className={`ml-2 mt-1 h-3.5 w-3.5 shrink-0 text-fg-subtle transition-transform ${
                      isOpen ? 'rotate-180' : ''
                    }`}
                    aria-hidden="true"
                  />
                </button>

                <a
                  href={row.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${row.company} takvim sayfası`}
                  className="mr-3 mt-3 shrink-0 text-fg-subtle transition-colors hover:text-fg"
                >
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>

              {isOpen && <IpoDetailPanel row={row} />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
