'use client';

import { AlertTriangle, ChevronDown, Crosshair, Loader2, Search, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import StaleStrip from '@/components/ui/StaleStrip';
import StatusMessage from '@/components/ui/StatusMessage';
import ToggleGroup from '@/components/ui/ToggleGroup';
import {
  useBistRadar,
  useBistRadarJob,
  useCancelBistRadarScan,
  useStartBistRadarScan,
} from '@/hooks/useBist';
import { RADAR_HORIZONS, type RadarHorizon } from '@/lib/bist-api';
import { formatDateTime } from '@/lib/bist-format';
import { depthNote, memosPending, rejectionText, summaryLine, voicesNote } from '@/lib/bist-radar';
import BistPageShell from '../BistPageShell';
import RadarCandidateCard from './RadarCandidateCard';
import RadarScanProgress from './RadarScanProgress';
import RadarUniverseTable from './RadarUniverseTable';

/**
 * The Radar: one button, the XU100 scanned, the pullbacks-in-uptrends listed.
 *
 * Three things the page holds to:
 *
 * * **The last scan is shown before anything is pressed.** A scan costs a
 *   minute and a few hundred requests; the tab is opened far more often than
 *   it is re-run. The header says when the read was taken.
 * * **A running scan does not blank the page.** The previous result stays up
 *   with the progress beside it, and the new one replaces it as soon as the
 *   scores exist — memos then fill in one by one.
 * * **No candidates is a result, not an empty state.** The page says so in
 *   words and names the three nearest misses, so a quiet day reads as a quiet
 *   day rather than as a broken scan.
 */
export default function BistRadarPage() {
  const [horizon, setHorizon] = useState<RadarHorizon>('swing');
  const [jobId, setJobId] = useState<string | undefined>();
  const [universeOpen, setUniverseOpen] = useState(false);

  const last = useBistRadar(horizon);
  const start = useStartBistRadarScan();
  const cancel = useCancelBistRadarScan();
  const job = useBistRadarJob(jobId);

  // A job started for another horizon is not this tab's job any more.
  useEffect(() => {
    if (job.data && job.data.horizon !== horizon) setJobId(undefined);
  }, [horizon, job.data]);

  const running = !!job.data && (job.data.status === 'queued' || job.data.status === 'running');
  const result = last.data;
  const noScanYet = last.isError && !result;
  const cancelled = job.data?.status === 'error' && /cancel/i.test(job.data.error ?? '');
  const failed = job.data?.status === 'error' && !cancelled ? job.data.error : null;

  const onScan = () => {
    start.mutate(horizon, { onSuccess: (started) => setJobId(started.jobId) });
  };

  // The same button, both ways: pressing it while a scan runs stops the scan.
  // A disabled "Taranıyor" left the reader with a minute they could not take
  // back, which is the one thing a button that started it should never do.
  const onCancel = () => {
    if (jobId) cancel.mutate(jobId);
  };

  return (
    <BistPageShell
      title="Radar"
      description="XU100 içinde yükseliş trendindeyken desteğe geri çekilmiş hisseler; giriş bandı, stop ve hedeflerle."
      delayed
      action={
        <div className="flex items-center gap-3">
          <ToggleGroup
            label="Ufuk"
            options={RADAR_HORIZONS.map((option) => ({ ...option }))}
            value={horizon}
            onChange={setHorizon}
          />
          {running ? (
            <button
              type="button"
              onClick={onCancel}
              disabled={cancel.isPending}
              title="Taramayı iptal et"
              className="group flex items-center gap-1.5 rounded-md border border-line-strong bg-surface-2 px-3 py-1.5 text-sm text-fg transition-colors hover:border-down disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Loader2 className="h-3.5 w-3.5 animate-spin group-hover:hidden" aria-hidden="true" />
              <X className="hidden h-3.5 w-3.5 text-down group-hover:block" aria-hidden="true" />
              <span className="group-hover:hidden">Taranıyor</span>
              <span className="hidden group-hover:inline">İptal</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onScan}
              disabled={start.isPending}
              className="flex items-center gap-1.5 rounded-md border border-line-strong bg-surface-2 px-3 py-1.5 text-sm text-fg transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-60"
            >
              {start.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Crosshair className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              Tara
            </button>
          )}
        </div>
      }
    >
      {result && (
        <StaleStrip
          stale
          asOf={result.scanned_at}
          labels={{
            stale: 'Son tarama',
            failed: 'Son tarama',
            retry: 'Yeniden tara',
            unknownAge: 'bir süre',
            suffix: 'önce',
          }}
          onRetry={running ? undefined : onScan}
        />
      )}

      {running && job.data && <RadarScanProgress job={job.data} />}

      {failed && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-down/40 bg-surface px-3 py-2 text-xs text-fg"
        >
          <AlertTriangle className="h-3 w-3 text-down" aria-hidden="true" />
          Tarama tamamlanamadı: {failed}
        </div>
      )}

      {noScanYet && !running && (
        <div className="surface surface-flat">
          <StatusMessage
            icon={Search}
            action={
              <button
                type="button"
                onClick={onScan}
                disabled={start.isPending}
                className="rounded-md border border-line px-3 py-1 text-sm text-fg transition-colors hover:border-line-strong"
              >
                Taramayı başlat
              </button>
            }
          >
            Bu ufuk için henüz tarama yapılmadı. Tarama bir dakika kadar sürer; sonuç saklanır.
          </StatusMessage>
        </div>
      )}

      {last.isLoading && !result && !noScanYet && <div className="shimmer h-40 rounded-md" />}

      {result && (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-fg-muted">
            <span>
              {summaryLine(result)} Ufuk: {result.horizon_label}. Trend filtresini{' '}
              <span className="tabnum">{result.counts.gate_passed}</span>, teknik kurulumu{' '}
              <span className="tabnum">{result.counts.technical_passed}</span> hisse geçti
              {result.counts.vetoed > 0 && (
                <>
                  , <span className="tabnum">{result.counts.vetoed}</span> temel vetoyla düştü
                </>
              )}
              .
            </span>
            <span className="text-2xs text-fg-subtle">{formatDateTime(result.scanned_at)}</span>
          </div>

          {depthNote(result) && (
            <p className="flex items-center gap-2 text-2xs text-warn">
              <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
              {depthNote(result)}
            </p>
          )}
          {voicesNote(result) && <p className="text-2xs text-fg-subtle">{voicesNote(result)}</p>}
          {!result.kap_checked && (
            <p className="text-2xs text-fg-subtle">
              KAP bildirimleri bu taramada kontrol edilemedi; bedelli ve tedbir vetoları
              uygulanmadı.
            </p>
          )}

          {result.candidates.length > 0 ? (
            <section className="space-y-3">
              <div className="flex items-baseline justify-between">
                <h2 className="label">Radar adayları · {result.candidates.length}</h2>
                {memosPending(result) && (
                  <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">
                    <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                    Yorumlar yazılıyor {result.memos.done}/{result.memos.total}
                  </span>
                )}
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {result.candidates.map((candidate) => (
                  <RadarCandidateCard key={candidate.ticker} candidate={candidate} />
                ))}
              </div>
            </section>
          ) : (
            <section className="surface surface-flat p-4">
              <h2 className="label mb-2">Bugün kurulum yok</h2>
              <p className="text-sm text-fg-muted">
                Taranan {result.universe_size} hissenin hiçbiri bu ufkun kurallarını birlikte
                karşılamadı. Bu bir sonuçtur; eşik düşürülerek liste doldurulmaz.
              </p>
              {result.nearest.length > 0 && (
                <ul className="mt-3 space-y-1 text-xs">
                  {result.nearest.map((row) => (
                    <li key={row.ticker} className="flex items-baseline justify-between gap-3">
                      <span className="font-medium text-fg">{row.ticker}</span>
                      <span className="truncate text-fg-muted">{rejectionText(row)}</span>
                      <span className="tabnum text-fg-subtle">{row.score_total ?? '—'}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section className="surface surface-flat overflow-hidden">
            <button
              type="button"
              onClick={() => setUniverseOpen((open) => !open)}
              aria-expanded={universeOpen}
              className="flex w-full items-center justify-between px-3 py-2 text-left"
            >
              <span className="label">Tüm evren · {result.universe.length} hisse</span>
              <ChevronDown
                className={`h-3.5 w-3.5 text-fg-subtle transition-transform ${
                  universeOpen ? 'rotate-180' : ''
                }`}
                aria-hidden="true"
              />
            </button>
            {universeOpen && (
              <div className="border-t border-line">
                <RadarUniverseTable rows={result.universe} />
                <p className="px-3 py-2 text-2xs text-fg-subtle">
                  * Mali tablo okunamadı; temel puan yalnızca çarpanlara dayanıyor.
                </p>
              </div>
            )}
          </section>
        </>
      )}
    </BistPageShell>
  );
}
