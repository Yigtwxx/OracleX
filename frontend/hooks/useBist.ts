'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/hooks/queries';
import { aiNotePollInterval } from '@/lib/ai-note';
import {
  fetchBistCalendar,
  fetchBistFinancials,
  fetchBistFinancialsNote,
  fetchBistFund,
  fetchBistFundHoldings,
  fetchBistFundComparison,
  fetchBistFunds,
  fetchBistFundsMarketNote,
  fetchBistHeatmap,
  fetchBistMarketNote,
  fetchBistKap,
  fetchBistKapNote,
  fetchBistMacro,
  fetchBistMacroNote,
  fetchBistNightShift,
  fetchBistOverview,
  fetchBistPositioning,
  fetchBistPositioningNote,
  fetchBistRestrictions,
  fetchBistStock,
  fetchBistStocks,
  fetchBistViop,
  fetchBistViopMap,
  fetchBistViopNote,
  fetchBistViopMapNote,
  fetchBistViopUnderlyings,
  fetchBistOwnershipBoard,
  fetchBistOwnershipEntity,
  fetchBistOwnershipMoves,
  fetchBistAssetOwners,
  fetchBistOwnershipNote,
  cancelBistRadarScan,
  fetchBistRadar,
  fetchBistRadarJob,
  startBistRadarScan,
  type RadarHorizon,
  type RadarJob,
  type BistFundsQuery,
  type BistKapQuery,
  type BistStocksQuery,
} from '@/lib/bist-api';

/**
 * Data hooks for the Borsa İstanbul realm.
 *
 * Every page on this realm renders its own failure surface — an empty screener
 * has to say *why* it is empty — so every query here is `meta: SILENT`. Without
 * it the global handler in `lib/queryClient.ts` raises a toast as well and the
 * reader is told about the same outage twice.
 *
 * Cadences are set against how often the underlying data actually changes, not
 * against how live the page should feel:
 *
 * * **Equities** are delayed fifteen minutes at the exchange, so polling faster
 *   than two minutes buys nothing but load.
 * * **Funds** price once a day, after the close. A refetch interval would be
 *   pure waste; the long `staleTime` is the point.
 * * **KAP** is the only genuinely live feed here — filings arrive through the
 *   session — so it is the only one polled at a minute.
 *
 * Global defaults (`retry: 3`, `gcTime`, `refetchOnWindowFocus`) come from
 * `lib/queryClient.ts:60-72` and are deliberately not repeated.
 */

const SILENT = { silentError: true } as const;

/** Delayed data; a shorter poll would only add load. */
const EQUITY_STALE_MS = 30 * 1000;
const EQUITY_POLL_MS = 120 * 1000;

/** Net asset values publish once, after the close. */
const FUND_STALE_MS = 15 * 60 * 1000;

/** The one live feed on the realm. */
const KAP_POLL_MS = 60 * 1000;

/**
 * How long a KAP result outlives the tab that fetched it.
 *
 * The global `gcTime` is five minutes, which is shorter than a reader spends on
 * the rest of the realm — so leaving KAP for Hisseler and coming back dropped
 * the tape and repainted the cold "Bildirimler yükleniyor…" state every time.
 * The filings behind it are immutable and the poll refreshes them on mount, so
 * holding them for half an hour costs a few hundred rows of memory and buys an
 * instant repaint.
 */
const KAP_GC_MS = 30 * 60 * 1000;

/** Macro prints monthly at best; the policy rate moves eight times a year. */
const MACRO_STALE_MS = 30 * 60 * 1000;

export function useBistOverview(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistOverview,
    queryFn: fetchBistOverview,
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    enabled,
    meta: SILENT,
  });
}

/**
 * The equity board read as a whole, with the sentence that explains it.
 *
 * Not parameterised by the screener's filters. The read is whether the index
 * and the breadth agree, which is a property of the whole board — a per-filter
 * version would answer a question nobody asked and multiply the note cache by
 * every combination of index and sector.
 *
 * Two cadences, as on `useMacroRegime`: while the sentence is being written it
 * looks again every few seconds, and once the run settles it drops back to the
 * equity cadence. On `unavailable` it stops entirely, so a tab left open
 * against a dead provider does not re-ask forever.
 */
export function useBistMarketNote(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistMarketNote,
    queryFn: fetchBistMarketNote,
    staleTime: EQUITY_STALE_MS,
    enabled,
    meta: SILENT,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? EQUITY_POLL_MS : generating;
    },
  });
}

/**
 * The same, for one fund universe.
 *
 * Keyed on the fund type because Yatırım, Emeklilik and BYF are different
 * universes with different mandates, and a median across all three would
 * describe none of them. No base polling interval: net asset values publish
 * once after the close, so there is nothing to poll for once the note lands.
 */
export function useBistFundsMarketNote(fundType: string, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistFundsMarketNote(fundType),
    queryFn: () => fetchBistFundsMarketNote(fundType),
    staleTime: FUND_STALE_MS,
    enabled,
    meta: SILENT,
    refetchInterval: (query) => aiNotePollInterval(query.state.data?.note),
  });
}

export function useBistStocks(query: BistStocksQuery = {}, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistStocks(query as Record<string, unknown>),
    queryFn: () => fetchBistStocks(query),
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    // Previous rows stay on screen while a new filter resolves, so changing a
    // sector does not blank the table for a beat.
    placeholderData: (previous) => previous,
    enabled,
    meta: SILENT,
  });
}

export function useBistHeatmap(index: string, limit: number = 150, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistHeatmap(index, limit),
    queryFn: () => fetchBistHeatmap({ index, limit }),
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    // The previous board stays up while a new index resolves. A treemap that
    // empties and refills reads as every tile moving at once, which is exactly
    // what the layout is meant to make meaningful.
    placeholderData: (previous) => previous,
    enabled,
    meta: SILENT,
  });
}

export function useBistStock(ticker: string | null, range: string = '1y') {
  return useQuery({
    queryKey: queryKeys.bistStock(ticker ?? '', range),
    queryFn: () => fetchBistStock(ticker as string, range),
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    enabled: !!ticker,
    // An unlisted ticker answers 404 and will keep answering 404; retrying
    // three times only delays the message.
    retry: false,
    meta: SILENT,
  });
}

export function useBistFunds(query: BistFundsQuery = {}, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistFunds(query as Record<string, unknown>),
    queryFn: () => fetchBistFunds(query),
    staleTime: FUND_STALE_MS,
    placeholderData: (previous) => previous,
    enabled,
    meta: SILENT,
  });
}

export function useBistFund(code: string | null, months: number = 12) {
  return useQuery({
    queryKey: queryKeys.bistFund(code ?? '', months),
    queryFn: () => fetchBistFund(code as string, months),
    staleTime: FUND_STALE_MS,
    enabled: !!code,
    retry: false,
    meta: SILENT,
  });
}

/**
 * What a fund actually owns, from its monthly KAP filing.
 *
 * Its own query rather than a field on `useBistFund`, because the two have
 * nothing in common but the fund: this one can cost four upstream calls and a
 * PDF parse on a cold cache, and the detail page must draw its chart without
 * waiting for it.
 *
 * An hour of `staleTime` against a source that publishes monthly, and `retry:
 * false` because the route always answers 200 — a fund with no readable filing
 * is a described absence, not a failure to retry.
 */
export function useBistFundHoldings(code: string | null, fundType: string = 'YAT') {
  return useQuery({
    queryKey: queryKeys.bistFundHoldings(code ?? ''),
    queryFn: () => fetchBistFundHoldings(code as string, fundType),
    staleTime: 60 * 60 * 1000,
    enabled: !!code,
    retry: false,
    meta: SILENT,
  });
}

export function useBistFundComparison(codes: string[], months: number = 12) {
  return useQuery({
    queryKey: queryKeys.bistFundComparison(codes, months),
    queryFn: () => fetchBistFundComparison(codes, months),
    staleTime: FUND_STALE_MS,
    enabled: codes.length > 0,
    meta: SILENT,
  });
}

export function useBistMacro(fxRange: string = '5y', enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistMacro(fxRange),
    queryFn: () => fetchBistMacro(fxRange),
    staleTime: MACRO_STALE_MS,
    enabled,
    meta: SILENT,
  });
}

/**
 * The read above the macro tiles. Same dual cadence as the other board-wide
 * notes: every few seconds while the model is writing, the equity cadence once
 * it has settled, and nothing at all on `unavailable`.
 */
export function useBistMacroNote(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistMacroNote,
    queryFn: fetchBistMacroNote,
    staleTime: MACRO_STALE_MS,
    enabled,
    meta: SILENT,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? EQUITY_POLL_MS : generating;
    },
  });
}

export function useBistKap(query: BistKapQuery = {}, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistKap(query as Record<string, unknown>),
    queryFn: () => fetchBistKap(query),
    staleTime: 30 * 1000,
    refetchInterval: KAP_POLL_MS,
    gcTime: KAP_GC_MS,
    placeholderData: (previous) => previous,
    enabled,
    meta: SILENT,
  });
}

/**
 * The model's read of one KAP filing, fetched only once a reader asks for it.
 *
 * `enabled` on a null index is the whole design. The tape renders sixty rows
 * and a reader opens one; a hook that fired per row would ask a local model to
 * write sixty paragraphs nobody requested, at tens of seconds each.
 *
 * A filing never changes, so the answer is good forever once it lands —
 * `staleTime: Infinity`, and the only polling is the few seconds while the
 * sentence is being written. On `unavailable` the polling stops rather than
 * re-asking a provider chain already known to be down.
 */
export function useBistKapNote(index: number | null) {
  return useQuery({
    queryKey: queryKeys.bistKapNote(index ?? 0),
    queryFn: () => fetchBistKapNote(index as number),
    staleTime: Infinity,
    enabled: index !== null,
    meta: SILENT,
    refetchInterval: (query) => aiNotePollInterval(query.state.data?.note),
  });
}

/**
 * The board-wide read above the VİOP page.
 *
 * Its own query rather than a field on `useBistViop`, mirroring the endpoint
 * split: the board is cached for five minutes and polled, and a note welded to
 * it would tie one cadence to the other. Between runs it follows the board's
 * own interval, and while a note is being written it looks again every few
 * seconds. On `unavailable` it stops entirely, so a tab left open against a
 * dead provider does not re-ask forever.
 */
export function useBistViopNote(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistViopNote,
    queryFn: fetchBistViopNote,
    staleTime: EQUITY_STALE_MS,
    enabled,
    meta: SILENT,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? EQUITY_POLL_MS : generating;
    },
  });
}

export function useBistViopUnderlyings(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistViopUnderlyings,
    queryFn: fetchBistViopUnderlyings,
    // The universe changes when a contract is listed or delisted, which is a
    // matter of months, not minutes.
    staleTime: 60 * 60 * 1000,
    enabled,
    meta: SILENT,
  });
}

export function useBistViopMap(ticker: string, sessions: number = 120, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistViopMap(ticker, sessions),
    queryFn: () => fetchBistViopMap(ticker, sessions),
    // The bulletin publishes once, after the close. Polling faster than the
    // equity board would only add load against a public archive.
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    // The previous board stays up while a new symbol resolves — a chart that
    // empties and refills reads as the market moving.
    placeholderData: (previous) => previous,
    enabled: enabled && !!ticker,
    meta: SILENT,
  });
}

/**
 * The read above one underlying's margin map, keyed the way the map is.
 *
 * Switching the picker resolves a different note rather than re-labelling the
 * old one, which is why there is no `placeholderData` here: a paragraph about
 * THYAO shown under SASA's field for a second would be worse than a shimmer.
 */
/**
 * One company's statements.
 *
 * A long stale time and no poll: İş Yatırım publishes four times a year, and
 * the price header beside the charts is the only thing on the page that moves
 * intraday — it arrives with this payload rather than through a second query,
 * because a header refreshing on its own cadence would retire the whole board's
 * cache every two minutes for one number.
 */
export function useBistFinancials(ticker: string, quarters: number = 12, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistFinancials(ticker, quarters),
    queryFn: () => fetchBistFinancials(ticker, quarters),
    staleTime: FUND_STALE_MS,
    enabled: enabled && !!ticker,
    meta: SILENT,
  });
}

export function useBistFinancialsNote(ticker: string, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistFinancialsNote(ticker),
    queryFn: () => fetchBistFinancialsNote(ticker),
    staleTime: FUND_STALE_MS,
    enabled: enabled && !!ticker,
    meta: SILENT,
    refetchInterval: (query) => aiNotePollInterval(query.state.data?.note),
  });
}

export function useBistViopMapNote(
  ticker: string,
  sessions: number = 120,
  enabled: boolean = true
) {
  return useQuery({
    queryKey: queryKeys.bistViopMapNote(ticker, sessions),
    queryFn: () => fetchBistViopMapNote(ticker, sessions),
    staleTime: EQUITY_STALE_MS,
    enabled: enabled && !!ticker,
    meta: SILENT,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? EQUITY_POLL_MS : generating;
    },
  });
}

export function useBistRestrictions(limit: number = 30, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistRestrictions(limit),
    queryFn: () => fetchBistRestrictions(limit),
    staleTime: 5 * 60 * 1000,
    enabled,
    meta: SILENT,
  });
}

export function useBistViop(underlying?: string, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistViop(underlying),
    queryFn: () => fetchBistViop(underlying),
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    enabled,
    meta: SILENT,
  });
}

export function useBistCalendar(daysAhead: number = 90, daysBack: number = 14) {
  return useQuery({
    queryKey: queryKeys.bistCalendar(daysAhead, daysBack),
    queryFn: () => fetchBistCalendar(daysAhead, daysBack),
    // Dated events do not move intraday.
    staleTime: MACRO_STALE_MS,
    meta: SILENT,
  });
}

export function useBistPositioning(limit: number = 50, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistPositioning(limit),
    queryFn: () => fetchBistPositioning(limit),
    staleTime: EQUITY_STALE_MS,
    refetchInterval: EQUITY_POLL_MS,
    enabled,
    meta: SILENT,
  });
}

/**
 * What the positioning board as a whole says.
 *
 * Deliberately not parameterised by the board's `limit`. Those rows are ranked
 * by crowding, so any limit is a biased sample — the note is computed across
 * every listing, and a key carrying the limit would cache three different
 * answers to the same question.
 *
 * Two cadences, as on `useBistMarketNote`: while the sentence is being written
 * it looks again every few seconds, and once the run settles it drops back to
 * the equity cadence. On `unavailable` it stops entirely, so a tab left open
 * against a dead provider does not re-ask forever.
 */
export function useBistPositioningNote(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistPositioningNote,
    queryFn: fetchBistPositioningNote,
    staleTime: EQUITY_STALE_MS,
    enabled,
    meta: SILENT,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? EQUITY_POLL_MS : generating;
    },
  });
}

/**
 * Gece Mesaisi Endeksi.
 *
 * Polled on the hour because the service caches for exactly that: the Resmî
 * Gazette publishes once a day and the presidency feed a handful of times, so
 * a faster poll re-reads the same day at the cost of sixteen requests to a
 * government host.
 */
export function useBistNightShift(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistNightShift,
    queryFn: fetchBistNightShift,
    staleTime: 30 * 60 * 1000,
    refetchInterval: 60 * 60 * 1000,
    enabled,
    meta: SILENT,
  });
}

/**
 * The ownership board rebuilds once a day on the server, so nothing here
 * polls: a long `staleTime` and no interval, the same cadence the global
 * `/ownership` hooks keep.
 */
const OWNERSHIP_STALE_MS = 30 * 60 * 1000;

export function useBistOwnershipBoard(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistOwnershipBoard,
    queryFn: fetchBistOwnershipBoard,
    staleTime: OWNERSHIP_STALE_MS,
    enabled,
    retry: false,
    meta: SILENT,
  });
}

export function useBistOwnershipEntity(entityId: string | null) {
  return useQuery({
    queryKey: queryKeys.bistOwnershipEntity(entityId ?? ''),
    queryFn: () => fetchBistOwnershipEntity(entityId as string),
    staleTime: OWNERSHIP_STALE_MS,
    enabled: !!entityId,
    retry: false,
    meta: SILENT,
  });
}

export function useBistOwnershipMoves(
  limit: number = 20,
  ticker?: string,
  enabled: boolean = true
) {
  return useQuery({
    queryKey: queryKeys.bistOwnershipMoves(limit, ticker),
    queryFn: () => fetchBistOwnershipMoves(limit, ticker),
    staleTime: KAP_POLL_MS,
    refetchInterval: KAP_POLL_MS,
    enabled,
    meta: SILENT,
  });
}

/**
 * Who holds one company. `retry: false` because the two failures it can
 * answer with — 404 outside the XU100, 503 before the board exists — are both
 * facts, and retrying a fact three times only delays the sentence.
 */
export function useBistAssetOwners(ticker: string | null, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistAssetOwners(ticker ?? ''),
    queryFn: () => fetchBistAssetOwners(ticker as string),
    staleTime: OWNERSHIP_STALE_MS,
    enabled: enabled && !!ticker,
    retry: false,
    meta: SILENT,
  });
}

/**
 * What the ownership board as a whole says.
 *
 * Polls a few seconds apart while the paragraph is being written, then settles
 * to the board's own half-hour cadence; on `unavailable` it stops entirely, so
 * a tab left open against a dead provider does not re-ask forever.
 */
export function useBistOwnershipNote(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.bistOwnershipNote,
    queryFn: fetchBistOwnershipNote,
    staleTime: OWNERSHIP_STALE_MS,
    enabled,
    meta: SILENT,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? OWNERSHIP_STALE_MS : generating;
    },
  });
}

// ── Radar ──────────────────────────────────────────────────────────────────

/** How often a running scan is polled. Matches the report job poll. */
const RADAR_JOB_POLL_MS = 1500;

/**
 * The last finished scan for a horizon.
 *
 * A 404 here is the normal cold state — no scan has ever run for this horizon
 * — so it must not toast, and it must not retry: retrying a "not yet" three
 * times only delays the button the reader needs to see.
 */
export function useBistRadar(horizon: RadarHorizon) {
  return useQuery({
    queryKey: queryKeys.bistRadar(horizon),
    queryFn: () => fetchBistRadar(horizon),
    staleTime: 5 * 60 * 1000,
    retry: false,
    meta: SILENT,
  });
}

export function useStartBistRadarScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (horizon: RadarHorizon) => startBistRadarScan(horizon),
    onSuccess: (job: RadarJob) => {
      queryClient.setQueryData(queryKeys.bistRadarJob(job.jobId), job);
    },
  });
}

/**
 * Poll a running scan.
 *
 * The scan publishes its result as soon as scoring has run and again after
 * each memo, so every poll that carries a result is written straight into the
 * horizon's cache — the page fills in while the job is still marked running.
 */
export function useBistRadarJob(jobId: string | undefined) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.bistRadarJob(jobId ?? ''),
    queryFn: async () => {
      const job = await fetchBistRadarJob(jobId!);
      if (job.result) {
        queryClient.setQueryData(queryKeys.bistRadar(job.horizon), job.result);
      }
      return job;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? RADAR_JOB_POLL_MS : false;
    },
    retry: false,
    gcTime: 0,
    meta: SILENT,
  });
}

/**
 * Stop a running scan.
 *
 * The settled job is written over the poll's cache entry so the button flips
 * back on the spot rather than after one more tick; the horizon's last result
 * is untouched because a cancelled scan persisted nothing.
 */
export function useCancelBistRadarScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelBistRadarScan(jobId),
    onSuccess: (job: RadarJob) => {
      queryClient.setQueryData(queryKeys.bistRadarJob(job.jobId), job);
    },
  });
}
