'use client';

import { useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchOnChainData,
  fetchFundingRates,
  fetchLiquidations,
  fetchLiquidationMap,
  fetchHeatmapData,
  fetchMacroCalendar,
  fetchMacroBoard,
  fetchLiveEvents,
  fetchLiveStreams,
  fetchLiveStreamers,
  fetchLiveTape,
  fetchMarketOverview,
  fetchFearGreedIndex,
  fetchNasdaqOverview,
  fetchNews,
  fetchWatchlists,
  createWatchlist,
  deleteWatchlist,
  fetchAnalysisReport,
  fetchReportSummaries,
  startAnalysisJob,
  fetchAnalysisJob,
  fetchActiveAnalysisJobs,
  cancelAnalysisJob,
  fetchChatJob,
  startNewsAnalysisJob,
  fetchNewsAnalysisJob,
  fetchCachedNewsAnalysis,
  fetchNotes,
  createNote,
  deleteNote,
  fetchOwnershipBoard,
  fetchOwnershipEntity,
  fetchOwnershipConsensus,
  fetchAssetOwners,
  fetchWatchlistOverlap,
  type TimeFrame,
  type Note,
  type AnalysisJob,
  type NewsAnalysis,
  type NewsAnalysisJob,
} from '@/lib/api';

// ==========================================
// Query Keys — centralized for consistency
// ==========================================
export const queryKeys = {
  onChainData: ['onChainData'] as const,
  fundingRates: ['fundingRates'] as const,
  liquidations: ['liquidations'] as const,
  liquidationMap: (symbol: string, interval: string) =>
    ['liquidationMap', symbol, interval] as const,
  heatmap: (limit: number, includePegged: boolean) => ['heatmap', limit, includePegged] as const,
  macroCalendar: ['macroCalendar'] as const,
  macroBoard: ['macroBoard'] as const,
  liveEvents: ['liveEvents'] as const,
  liveStreams: ['liveStreams'] as const,
  liveStreamers: ['liveStreamers'] as const,
  liveTape: (limit: number) => ['liveTape', limit] as const,
  marketOverview: ['marketOverview'] as const,
  fearGreedIndex: ['fearGreedIndex'] as const,
  nasdaqOverview: ['nasdaqOverview'] as const,
  news: (assetType?: string) => ['news', assetType] as const,
  watchlists: ['watchlists'] as const,
  analysisReport: (timeframe: TimeFrame) => ['analysisReport', timeframe] as const,
  reportSummaries: ['reportSummaries'] as const,
  analysisJob: (jobId: string) => ['analysisJob', jobId] as const,
  activeAnalysisJobs: ['activeAnalysisJobs'] as const,
  chatJob: (jobId: string) => ['chatJob', jobId] as const,
  // Keyed by news id, which is what makes the panel race-proof: a late response
  // for item A is physically unable to render under item B.
  newsAnalysis: (newsId: string) => ['newsAnalysis', newsId] as const,
  newsAnalysisJob: (jobId: string) => ['newsAnalysisJob', jobId] as const,
  notes: ['notes'] as const,
  // Ownership. The board is rebuilt once a day on the server, so both keys are
  // long-lived — see useOwnershipBoard for why nothing here polls.
  ownershipBoard: ['ownershipBoard'] as const,
  ownershipEntity: (entityId: string) => ['ownershipEntity', entityId] as const,
  ownershipConsensus: ['ownershipConsensus'] as const,
  ownershipAsset: (symbol: string) => ['ownershipAsset', symbol] as const,
  ownershipWatchlistOverlap: ['ownershipWatchlistOverlap'] as const,
  // Community. The hooks live in hooks/useCommunity.ts, but the keys stay here
  // so there is one place to look when invalidating across features.
  // `scope` is the viewer id for the "My Posts" tab and 'all' for the board —
  // keeping it in the key stops one user's tab from serving another's cache.
  communityFeed: (sort: string, type: string, scope: string, symbol?: string) =>
    ['communityFeed', sort, type, scope, symbol ?? null] as const,
  communityPost: (postId: string) => ['communityPost', postId] as const,
  communityComments: (postId: string) => ['communityComments', postId] as const,
  communitySidebar: ['communitySidebar'] as const,
  // Admin. `adminSession` is fetched on every page load by the nav, so it is
  // cached forever and never retried — see hooks/useAdmin.ts.
  adminSession: ['adminSession'] as const,
  adminOverview: ['adminOverview'] as const,
  adminUsers: (filters: string) => ['adminUsers', filters] as const,
  adminPosts: (filters: string) => ['adminPosts', filters] as const,
  adminAudit: (offset: number) => ['adminAudit', offset] as const,
  // Profile. Keyed by user id for the same reason the community feed is: these
  // are per-account rows, and a signed-out/signed-in switch in one tab must not
  // serve the previous account's profile from cache.
  profile: (userId: string) => ['profile', userId] as const,
  // Keyed by the profile being *viewed*, not by the viewer: two people looking
  // at the same person should share one cache entry.
  publicProfile: (userId: string) => ['publicProfile', userId] as const,
  // Social. The hooks live in hooks/useSocial.ts; the keys stay here so the
  // places that invalidate across features have one list to read.
  //
  // None of these are keyed by viewer, unlike `profile`: every one of them is
  // already scoped to the caller's own JWT server-side, and a sign-out clears
  // the whole cache. `socialMessages` is keyed by conversation for the reason
  // the news panel is keyed by news id — a late response for one thread must be
  // physically unable to render under another.
  socialConversations: ['socialConversations'] as const,
  socialMessages: (conversationId: string) => ['socialMessages', conversationId] as const,
  socialUnread: ['socialUnread'] as const,
  socialEligibility: ['socialEligibility'] as const,
  socialActivity: ['socialActivity'] as const,
  socialBlocks: ['socialBlocks'] as const,
  userSettings: ['userSettings'] as const,
};

// ==========================================
// HOME PAGE HOOKS
// ==========================================

export function useOnChainData() {
  return useQuery({
    queryKey: queryKeys.onChainData,
    queryFn: fetchOnChainData,
    staleTime: 30 * 1000, // 30s
    refetchInterval: 60 * 1000, // 60s auto-refresh
  });
}

export function useFundingRates() {
  return useQuery({
    queryKey: queryKeys.fundingRates,
    queryFn: fetchFundingRates,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}

export function useLiquidations() {
  return useQuery({
    queryKey: queryKeys.liquidations,
    queryFn: fetchLiquidations,
    staleTime: 15 * 1000, // 15s — liquidations change fast
    refetchInterval: 30 * 1000,
  });
}

/**
 * Modelled liquidation heatmap for a symbol.
 *
 * The backend replays the whole window on a cache miss, so this is polled
 * gently — a new candle only lands once per interval anyway.
 */
export function useLiquidationMap(symbol: string, interval: string) {
  return useQuery({
    queryKey: queryKeys.liquidationMap(symbol, interval),
    queryFn: () => fetchLiquidationMap(symbol, interval),
    staleTime: 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
    enabled: Boolean(symbol),
  });
}

/**
 * The heatmap board.
 *
 * Polled on the backend's own refresh cadence rather than faster: the board is
 * rebuilt every five minutes in the background, so the minute-long poll this
 * replaced spent four requests out of five re-fetching an identical payload.
 *
 * `placeholderData` is what keeps a populated board on screen while a filter
 * change refetches, and react-query's retained `data` is what keeps it there
 * through a failed refresh — the component reads `isError && data` and shows a
 * staleness badge instead of blanking a working view.
 */
export function useHeatmap(limit = 50, includePegged = false) {
  return useQuery({
    queryKey: queryKeys.heatmap(limit, includePegged),
    queryFn: () => fetchHeatmapData(limit, includePegged),
    staleTime: 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    placeholderData: (previous) => previous,
  });
}

export function useMacroCalendar() {
  return useQuery({
    queryKey: queryKeys.macroCalendar,
    queryFn: fetchMacroCalendar,
    staleTime: 5 * 60 * 1000, // 5 min — macroeconomic events rarely change
  });
}

// ==========================================
// MACRO PAGE HOOKS
// ==========================================

/** Matches the server's own 120s board cache — polling faster only re-reads it. */
export function useMacroBoard() {
  return useQuery({
    queryKey: queryKeys.macroBoard,
    queryFn: fetchMacroBoard,
    staleTime: 60 * 1000,
    refetchInterval: 120 * 1000,
  });
}

// ==========================================
// LIVE PAGE HOOKS
// ==========================================

/**
 * The event calendar, polled faster while something is actually live.
 *
 * 60s matches the server's 15-minute cache closely enough for a schedule that
 * barely moves, but the live→ended transition is the one moment on this page
 * where a stale minute is visible — so the interval tightens exactly then, and
 * only then.
 */
export function useLiveEvents() {
  return useQuery({
    queryKey: queryKeys.liveEvents,
    queryFn: fetchLiveEvents,
    staleTime: 30 * 1000,
    refetchInterval: (query) => ((query.state.data?.live.length ?? 0) > 0 ? 20 * 1000 : 60 * 1000),
  });
}

/** Matches the probe's own cadence; polling faster only re-reads its cache. */
export function useLiveStreams() {
  return useQuery({
    queryKey: queryKeys.liveStreams,
    queryFn: fetchLiveStreams,
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });
}

/**
 * The streamer board.
 *
 * `enabled` is the whole cost story: each refresh probes twenty YouTube channel
 * pages server-side, so the query is wired to the sub-tab being open and does
 * nothing at all while the user is looking at the calendar. The interval then
 * matches the server's ten-minute cache, so an open tab mostly re-reads it.
 */
export function useLiveStreamers(enabled = true) {
  return useQuery({
    queryKey: queryKeys.liveStreamers,
    queryFn: fetchLiveStreamers,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
    enabled,
  });
}

/**
 * The headline tape.
 *
 * Polled faster than anything else on the page and it costs nothing to: the
 * endpoint reads the news cache the scheduler already refreshes, so a 20s poll
 * never reaches an upstream.
 */
export function useLiveTape(limit = 50) {
  return useQuery({
    queryKey: queryKeys.liveTape(limit),
    queryFn: () => fetchLiveTape(limit),
    staleTime: 15 * 1000,
    refetchInterval: 20 * 1000,
  });
}

// ==========================================
// OVERVIEW PAGE HOOKS
// ==========================================

export function useMarketOverview(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.marketOverview,
    queryFn: fetchMarketOverview,
    staleTime: 30 * 1000,
    refetchInterval: 120 * 1000,
    enabled,
  });
}

export function useFearGreedIndex(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.fearGreedIndex,
    queryFn: fetchFearGreedIndex,
    staleTime: 2 * 60 * 1000, // 2 min
    enabled,
  });
}

export function useNasdaqOverview(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.nasdaqOverview,
    queryFn: fetchNasdaqOverview,
    staleTime: 30 * 1000,
    refetchInterval: 120 * 1000,
    enabled,
  });
}

// ==========================================
// NEWS HOOKS
// ==========================================

export function useNews(assetType?: string) {
  return useQuery({
    queryKey: queryKeys.news(assetType),
    queryFn: () => fetchNews(assetType),
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });
}

// ==========================================
// WATCHLIST HOOKS
// ==========================================

export function useWatchlists() {
  return useQuery({
    queryKey: queryKeys.watchlists,
    queryFn: fetchWatchlists,
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });
}

export function useCreateWatchlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      items,
    }: {
      name: string;
      items: { symbol: string; type: 'STOCK' | 'CRYPTO' }[];
    }) => createWatchlist(name, items),
    onSuccess: (data) => {
      // Update cache directly with the returned data
      queryClient.setQueryData(queryKeys.watchlists, data);
    },
  });
}

export function useDeleteWatchlist() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteWatchlist(id),
    onMutate: async (deletedId) => {
      // Optimistic update — remove from cache immediately
      await queryClient.cancelQueries({ queryKey: queryKeys.watchlists });
      const previous = queryClient.getQueryData(queryKeys.watchlists);
      queryClient.setQueryData(queryKeys.watchlists, (old: unknown) => {
        if (!Array.isArray(old)) return old;
        return old.filter((w: { id: string }) => w.id !== deletedId);
      });
      return { previous };
    },
    onError: (_err, _id, context) => {
      // Rollback on error
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.watchlists, context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.watchlists });
    },
  });
}

// ==========================================
// ANALYSIS PAGE HOOKS
// ==========================================

/** How often a running job is polled for its current stage. */
const JOB_POLL_INTERVAL_MS = 1500;

/**
 * Freshness of every stored report.
 *
 * This is the only analysis request the page makes on mount. Generation is
 * never triggered by a read — it costs minutes of LLM time and must be the
 * user's explicit choice.
 */
export function useReportSummaries() {
  return useQuery({
    queryKey: queryKeys.reportSummaries,
    queryFn: fetchReportSummaries,
    staleTime: 30 * 1000,
  });
}

/** Stored report for a timeframe. Disabled until the user picks one. */
export function useAnalysisReport(timeframe: TimeFrame | undefined) {
  return useQuery({
    queryKey: queryKeys.analysisReport(timeframe ?? 'daily'),
    queryFn: () => fetchAnalysisReport(timeframe!),
    enabled: !!timeframe,
    staleTime: 5 * 60 * 1000,
  });
}

export function useStartAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (timeframe: TimeFrame) => startAnalysisJob(timeframe),
    onSuccess: (job: AnalysisJob) => {
      queryClient.setQueryData(queryKeys.analysisJob(job.jobId), job);
      // Show the run as in-flight everywhere immediately, rather than after the
      // next active-jobs poll.
      queryClient.invalidateQueries({ queryKey: queryKeys.activeAnalysisJobs });
    },
  });
}

/**
 * Poll a running report job.
 *
 * Polling stops as soon as the job settles, and the finished report is written
 * straight into the report cache so the view can switch over without a refetch.
 */
export function useAnalysisJob(jobId: string | undefined) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.analysisJob(jobId ?? ''),
    queryFn: async () => {
      const job = await fetchAnalysisJob(jobId!);
      if (job.status === 'done' && job.result) {
        queryClient.setQueryData(queryKeys.analysisReport(job.timeframe), job.result);
        queryClient.invalidateQueries({ queryKey: queryKeys.reportSummaries });
      }
      return job;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? JOB_POLL_INTERVAL_MS : false;
    },
    // A job that expired server-side is gone for good; retrying just delays
    // the error the user needs to see.
    retry: false,
    gcTime: 0,
  });
}

/**
 * Stop a running report.
 *
 * The settled job is written over the poll's cache entry so the progress view
 * stops on the spot instead of showing one more stage tick, and the active list
 * is refetched so every other surface drops its spinner too.
 */
export function useCancelAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => cancelAnalysisJob(jobId),
    onSuccess: (job: AnalysisJob) => {
      queryClient.setQueryData(queryKeys.analysisJob(job.jobId), job);
      queryClient.invalidateQueries({ queryKey: queryKeys.activeAnalysisJobs });
    },
  });
}

/** How often the page asks which report runs are still in flight. */
const ACTIVE_JOBS_POLL_INTERVAL_MS = 4000;

/**
 * Report runs in flight, keyed off the server rather than page state.
 *
 * The job id lives in `AnalysisPage` state, so switching tabs unmounts the page
 * and loses it while the run keeps going. Polling this instead means a returning
 * page — or a reloaded browser — still knows which horizon is generating.
 *
 * A run that disappears from the list has just finished, so the report it
 * produced and the freshness card above it are refetched here; nothing else is
 * watching for that when the user was on another tab while it landed.
 */
export function useActiveAnalysisJobs() {
  const queryClient = useQueryClient();
  const runningRef = useRef<TimeFrame[]>([]);

  return useQuery({
    queryKey: queryKeys.activeAnalysisJobs,
    queryFn: async () => {
      const jobs = await fetchActiveAnalysisJobs();
      const running = jobs.map((job) => job.timeframe);
      const settled = runningRef.current.filter((timeframe) => !running.includes(timeframe));
      runningRef.current = running;

      if (settled.length > 0) {
        queryClient.invalidateQueries({ queryKey: queryKeys.reportSummaries });
        for (const timeframe of settled) {
          queryClient.invalidateQueries({ queryKey: queryKeys.analysisReport(timeframe) });
        }
      }
      return jobs;
    },
    refetchInterval: ACTIVE_JOBS_POLL_INTERVAL_MS,
    // A failed poll must not strand a spinner on a run that already ended.
    retry: false,
  });
}

// ==========================================
// CHAT JOB HOOKS
// ==========================================

/**
 * Faster than the report poll, on purpose.
 *
 * A report's stages change every minute or so and the payload carries the whole
 * report. A chat turn's steps are the product — the user is watching them — and
 * the payload is a few hundred bytes until the answer lands.
 */
const CHAT_JOB_POLL_INTERVAL_MS = 900;

/** Poll a running chat turn for its steps and, finally, its answer. */
export function useChatJob(jobId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.chatJob(jobId ?? ''),
    queryFn: () => fetchChatJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? CHAT_JOB_POLL_INTERVAL_MS : false;
    },
    // A job that expired server-side is gone for good, and a chat job is
    // retained for five minutes — retrying just delays the error.
    retry: false,
    gcTime: 0,
  });
}

// ==========================================
// NEWS ANALYSIS HOOKS
// ==========================================

/**
 * The stored note for a news item, or null when there isn't one yet.
 *
 * `fetchCachedNewsAnalysis` resolves the "no analysis yet" 404 to null rather
 * than throwing, so opening an unanalysed headline is not reported as a query
 * error — the global error handler turns any query error into a connection
 * toast, and that is the normal first-click state.
 *
 * `staleTime: Infinity` because the analysis is written into this cache by the
 * job poller — refetching would just undo that.
 */
export function useNewsAnalysis(newsId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.newsAnalysis(newsId ?? ''),
    queryFn: () => fetchCachedNewsAnalysis(newsId!),
    enabled: !!newsId,
    staleTime: Infinity,
  });
}

/** Kick off the pipeline for a news item. */
export function useStartNewsAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ newsId, currentPrice }: { newsId: string; currentPrice?: number }) =>
      startNewsAnalysisJob(newsId, currentPrice),
    onSuccess: (job: NewsAnalysisJob) => {
      queryClient.setQueryData(queryKeys.newsAnalysisJob(job.jobId), job);
      // A job that was already finished (a cached re-run) carries its result
      // immediately; publish it so the panel does not wait a poll interval.
      if (job.result) {
        queryClient.setQueryData(queryKeys.newsAnalysis(job.newsId), job.result);
      }
    },
  });
}

/**
 * Poll a running news analysis.
 *
 * Both the partial verdict and the final note are written into
 * `newsAnalysis(newsId)`, so the panel reads one key and never has to know
 * whether a job is in flight.
 */
export function useNewsAnalysisJob(jobId: string | undefined) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.newsAnalysisJob(jobId ?? ''),
    queryFn: async () => {
      const job = await fetchNewsAnalysisJob(jobId!);
      const analysis: NewsAnalysis | undefined = job.result ?? job.partialResult;
      if (analysis) {
        queryClient.setQueryData(queryKeys.newsAnalysis(job.newsId), analysis);
      }
      return job;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? JOB_POLL_INTERVAL_MS : false;
    },
    // An expired job is gone for good; retrying only delays the error.
    retry: false,
    gcTime: 0,
  });
}

export function useNotes() {
  return useQuery({
    queryKey: queryKeys.notes,
    queryFn: fetchNotes,
    staleTime: 60 * 1000,
  });
}

export function useCreateNote() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ title, content }: { title: string; content: string }) =>
      createNote(title, content),
    onSuccess: (notes: Note[]) => {
      queryClient.setQueryData(queryKeys.notes, notes);
    },
  });
}

export function useDeleteNote() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onSuccess: (notes: Note[]) => {
      queryClient.setQueryData(queryKeys.notes, notes);
    },
  });
}

// ==========================================
// OWNERSHIP HOOKS
// ==========================================

// The server rebuilds this board once a day from rate-limited public sources,
// so there is nothing for the client to poll for: a refetch would return the
// identical payload and cost a request against a budget shared by every user.
// Long staleTime, no interval, no refetch on focus.
const OWNERSHIP_STALE_TIME = 30 * 60 * 1000;

export function useOwnershipBoard() {
  return useQuery({
    queryKey: queryKeys.ownershipBoard,
    queryFn: fetchOwnershipBoard,
    staleTime: OWNERSHIP_STALE_TIME,
    refetchOnWindowFocus: false,
  });
}

/**
 * One entity's full position list.
 *
 * Keyed by entity id so a slow response for one card can never render under
 * another — the same reason the news analysis panel keys on news id.
 */
export function useOwnershipEntity(entityId: string | null) {
  return useQuery({
    queryKey: queryKeys.ownershipEntity(entityId ?? ''),
    queryFn: () => fetchOwnershipEntity(entityId as string),
    enabled: Boolean(entityId),
    staleTime: OWNERSHIP_STALE_TIME,
    refetchOnWindowFocus: false,
  });
}

export function useOwnershipConsensus() {
  return useQuery({
    queryKey: queryKeys.ownershipConsensus,
    queryFn: fetchOwnershipConsensus,
    staleTime: OWNERSHIP_STALE_TIME,
    refetchOnWindowFocus: false,
  });
}

/** Who else holds one asset. Keyed by symbol so two panels cannot cross wires. */
export function useAssetOwners(symbol: string | null) {
  return useQuery({
    queryKey: queryKeys.ownershipAsset(symbol ?? ''),
    queryFn: () => fetchAssetOwners(symbol as string),
    enabled: Boolean(symbol),
    staleTime: OWNERSHIP_STALE_TIME,
    refetchOnWindowFocus: false,
  });
}

/**
 * Overlap with the local watchlist.
 *
 * `silentError` because this panel hides itself when it has nothing: a toast
 * about a decorative strip failing would be noise, not information.
 */
export function useWatchlistOverlap() {
  return useQuery({
    queryKey: queryKeys.ownershipWatchlistOverlap,
    queryFn: fetchWatchlistOverlap,
    staleTime: OWNERSHIP_STALE_TIME,
    refetchOnWindowFocus: false,
    meta: { silentError: true },
  });
}
