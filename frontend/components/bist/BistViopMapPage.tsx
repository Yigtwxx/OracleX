'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Gauge, RefreshCw } from 'lucide-react';

import { useBistViopMap, useBistViopMapNote, useBistViopUnderlyings } from '@/hooks/useBist';
import { formatCompact, formatPercent } from '@/lib/bist-format';
import BistPageShell from '@/components/bist/BistPageShell';
import InferenceStrip from '@/components/bist/viop/InferenceStrip';
import ViopMapLegend from '@/components/bist/viop/ViopMapLegend';
import ViopMapNote from '@/components/bist/viop/ViopMapNote';
import ViopMarginMap from '@/components/bist/viop/ViopMarginMap';
import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup, { type ToggleOption } from '@/components/ui/ToggleGroup';

const WINDOWS: ToggleOption<string>[] = [
  { value: '60', label: '3 ay' },
  { value: '120', label: '6 ay' },
  { value: '160', label: '8 ay' },
];

/**
 * VİOP positioning against the scan range the clearing house publishes.
 *
 * The page's whole claim rests on one substitution: the crypto liquidation
 * board invents a distribution of leverage because no venue publishes what its
 * users chose, while Takasbank publishes a single scan range per underlying
 * that binds everyone. So the band is where a published parameter puts it, and
 * the only thing modelled here is which side opened — which the strip above the
 * chart says in its first three words.
 */
export default function BistViopMapPage() {
  const [ticker, setTicker] = useState('');
  const [sessions, setSessions] = useState('120');
  const [showProfile, setShowProfile] = useState(false);

  const universe = useBistViopUnderlyings();

  // The picker opens on whatever the newest session ranked first, rather than a
  // name frozen into the bundle — a contract that goes quiet drops out on its
  // own.
  useEffect(() => {
    if (!ticker && universe.data?.default?.length) {
      setTicker(universe.data.default[0]);
    }
  }, [ticker, universe.data]);

  const { data, isLoading, isError, error, refetch } = useBistViopMap(
    ticker,
    Number(sessions),
    !!ticker
  );
  const note = useBistViopMapNote(ticker, Number(sessions), !!ticker);

  const options: ToggleOption<string>[] = useMemo(
    () =>
      (universe.data?.default ?? []).map((code) => ({
        value: code,
        label: code,
      })),
    [universe.data]
  );

  const model = data?.model;

  const board = (() => {
    if (!ticker || (isLoading && !data)) {
      return <StatusMessage icon={RefreshCw}>Teminat haritası yükleniyor…</StatusMessage>;
    }
    if (isError && !data) {
      return (
        <StatusMessage
          icon={AlertTriangle}
          action={
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-1 rounded-md border border-line px-2.5 py-1 text-sm text-fg-muted hover:text-fg"
            >
              Tekrar dene
            </button>
          }
        >
          {error instanceof Error
            ? `Harita şu an oluşturulamıyor. (${error.message})`
            : 'Harita şu an oluşturulamıyor.'}
        </StatusMessage>
      );
    }
    if (data?.thin) {
      return (
        <StatusMessage icon={Gauge}>
          {data.ticker} üzerindeki açık pozisyon {formatCompact(data.open_interest)} sözleşme. Bu
          derinlikte harita birkaç günün pozisyonundan ibaret kalır; okunabilir bir kitap için
          yeterli değil.
        </StatusMessage>
      );
    }
    if (!data || data.cells.length === 0) {
      return (
        <StatusMessage icon={Gauge}>
          Bu pencerede yön atanabilen bir pozisyon açılışı yok.
        </StatusMessage>
      );
    }
    return <ViopMarginMap data={data} showProfile={showProfile} />;
  })();

  return (
    <BistPageShell
      title="Teminat Tarama Bantları"
      description="VİOP'ta açılan pozisyonlar, Takasbank'ın ilan ettiği tarama aralığı kadar uzağa çizilir. Yanında spotun gözlemlenmiş hacim profili."
      delayed
      action={
        data && (
          <span className="tabnum text-2xs text-fg-subtle">
            {data.model.sessions_covered} / {data.model.sessions_requested} seans
          </span>
        )
      }
    >
      <ViopMapNote data={note.data} isLoading={!!ticker && note.isLoading} />

      <div className="surface surface-flat overflow-hidden">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-3 py-2">
          {options.length > 0 && (
            <ToggleGroup label="Dayanak" options={options} value={ticker} onChange={setTicker} />
          )}
          {/* A rule, not more whitespace: the two groups choose different things
              and ran together as one long row of chips without it. */}
          <span aria-hidden="true" className="h-4 w-px shrink-0 bg-line-strong" />
          <ToggleGroup label="Pencere" options={WINDOWS} value={sessions} onChange={setSessions} />
          <button
            type="button"
            aria-pressed={showProfile}
            onClick={() => setShowProfile((current) => !current)}
            className={`rounded-md px-2.5 py-1 text-sm transition-colors ${
              showProfile ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
            }`}
          >
            Hacim profili
          </button>
          {model && (
            <span className="ml-auto flex items-baseline gap-1.5 text-2xs text-fg-subtle">
              <span>Tarama aralığı</span>
              <span className="tabnum text-sm font-semibold text-fg">
                {formatPercent(model.psr)}
              </span>
              <span>
                · {model.psr_as_of} run {model.psr_run}
              </span>
            </span>
          )}
        </div>

        {model && <InferenceStrip model={model} />}

        {data && (data.stale || isError) && (
          <div className="border-b border-line px-3 py-1">
            <StaleStrip
              stale={data.stale}
              refreshFailed={isError}
              asOf={data.as_of}
              onRetry={() => refetch()}
            />
          </div>
        )}

        {/* The claim a reader is most likely to get wrong, on one line. The
            reasoning behind it is reference material — true every visit, read
            once — so it opens on demand instead of occupying the space the
            chart needs. */}
        {model && (
          <details className="group border-b border-line">
            <summary className="flex cursor-pointer list-none items-baseline gap-1.5 px-3 py-1.5 text-2xs text-fg-muted hover:text-fg">
              <span className="text-fg">
                Bantlar teminat tamamlama çağrısı değil, tarama aralığıdır.
              </span>
              <span className="text-fg-subtle group-open:hidden">Nasıl hesaplandığı →</span>
              <span className="hidden text-fg-subtle group-open:inline">Kapat ↑</span>
            </summary>
            <p className="max-w-[80ch] px-3 pb-2 text-2xs leading-relaxed text-fg-muted">
              Bant, Takasbank&apos;ın {data?.ticker} için ilan ettiği{' '}
              <span className="tabnum text-fg">{formatPercent(model.psr)}</span> tarama aralığından
              (Price Scan Range, %99 güven / 1 gün) hesaplanır: fiyat oraya gelirse pozisyonun
              başlangıç teminatı, tarama riskini karşılamak üzere ayrıldığı hareketi tüketmiş olur.
              Çağrının tam olarak nerede tetikleneceği <span className="text-fg">hesaplanamaz</span>{' '}
              — Takasbank VİOP için sürdürme teminatı oranı yayınlamaz. Kaldıraç dağılımı
              varsayılmamıştır; oran yayınlanmıştır ve dayanak bazında değişir. Fiyat bir seviyeden
              geçtiğinde o seviye harcanmış sayılır ve haritadan düşer. Kaynak: {model.psr_source},{' '}
              {model.psr_as_of} run {model.psr_run}.
            </p>
          </details>
        )}

        {data?.warnings.includes('spot_intraday_unavailable') && (
          <div className="border-b border-line px-3 py-1 text-2xs text-fg-muted">
            Spot gün içi verisi şu an alınamıyor — hacim profili sütunu boş.
          </div>
        )}

        {model && model.sessions_covered < model.sessions_requested && (
          <div className="border-b border-line px-3 py-1 text-2xs text-fg-subtle">
            Bülten geçmişi {model.sessions_covered}/{model.sessions_requested} seans. Eksik günler
            arşivden henüz indirilmedi.
          </div>
        )}

        <div className="p-2">{board}</div>

        {data && (
          <div className="border-t border-line px-3 py-2">
            <ViopMapLegend hasProfile={showProfile && data.volume_profile !== null} />
            <p className="mt-1.5 text-2xs text-fg-subtle">
              {data.ticker} üzerine yazılı {data.expiries.length} vadenin tamamı tek eksende
              toplanmıştır. Her vadenin fiyatı, o günkü uzlaşma fiyatının aynı günün spot kapanışına
              oranıyla spot karşılığına çevrilir; aksi hâlde vadeli primi tek bir duvarı üç ayrı
              yere dağıtırdı.
              {showProfile && data.volume_profile && (
                <>
                  {' '}
                  Hacim profili {data.volume_profile.from} – {data.volume_profile.to} arasındaki{' '}
                  {data.volume_profile.interval}&apos;lik gün içi barlarından{' '}
                  <span className="text-fg-muted">gözlemlenmiştir</span>, modellenmemiştir.
                </>
              )}
            </p>
          </div>
        )}
      </div>
    </BistPageShell>
  );
}
