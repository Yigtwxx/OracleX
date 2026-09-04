'use client';

import { useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { aiNotePollInterval } from '@/lib/ai-note';
import { useOptionalAuth } from '@/contexts/AuthContext';
import {
  fetchAssetBrief,
  fetchFundingRates,
  fetchLiquidations,
  fetchLiquidationLines,
  fetchLiquidationProfile,
  type LiquidationExchange,
  type LiquidationVenue,
  fetchLiquidationMap,
  fetchOpenInterest,
  fetchDexPerps,
  fetchHeatmapData,
  fetchMacroCalendar,
  fetchMacroBoard,
  fetchElections,
  fetchMacroRegime,
  fetchNehIndex,
  fetchPizzaIndex,
  fetchPolymarketAnalysisJob,
  fetchPolymarketOriginJob,
  fetchPolymarketBoard,
  fetchPolymarketMap,
  fetchPolymarketMarket,
  startPolymarketAnalysis,
  startPolymarketOrigin,
  type PolymarketAnalysisJob,
  type PolymarketOriginJob,
  type PolymarketOriginReport,
  type PolymarketVerdict,
  fetchLiveEvents,
  fetchLiveStreams,
  fetchLiveStreamers,
  fetchLiveTape,
  fetchChainsBoard,
  fetchChainAnomalies,
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
  fetchOwnershipFlowNote,
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
  assetBrief: (symbol: string) => ['assetBrief', symbol] as const,
  fundingRates: ['fundingRates'] as const,
  liquidations: ['liquidations'] as const,
  liquidationMap: (symbol: string, interval: string, venue: string) =>
    ['liquidationMap', symbol, interval, venue] as const,
  // Keyed by columns as well: the levels view picks its window by trading
  // interval against column count, so two ranges can share an interval.
  liquidationLines: (symbol: string, interval: string, columns: number, venue: string) =>
    ['liquidationLines', symbol, interval, columns, venue] as const,
  liquidationProfile: (symbol: string, interval: string, columns: number, venue: string) =>
    ['liquidationProfile', symbol, interval, columns, venue] as const,
  openInterest: (symbol: string, interval: string) => ['openInterest', symbol, interval] as const,
  dexPerps: () => ['dexPerps'] as const,
  heatmap: (limit: number, includePegged: boolean) => ['heatmap', limit, includePegged] as const,
  macroCalendar: ['macroCalendar'] as const,
  macroBoard: ['macroBoard'] as const,
  // Named `macroRegime`, not `regimeNote`: `notes` below already means the notes
  // a user writes on a report, and the two must not read as the same thing.
  macroRegime: ['macroRegime'] as const,
  elections: ['elections'] as const,
  pizzaIndex: ['pizzaIndex'] as const,
  nehIndex: ['nehIndex'] as const,
  liveEvents: ['liveEvents'] as const,
  liveStreams: ['liveStreams'] as const,
  liveStreamers: ['liveStreamers'] as const,
  liveTape: (limit: number) => ['liveTape', limit] as const,
  chainsBoard: ['chainsBoard'] as const,
  chainAnomalies: ['chainAnomalies'] as const,
  marketOverview: ['marketOverview'] as const,
  // One symbol's price. Used only by the alarm engine — the board reads prices
  // from the overview and the websocket feed instead.
  symbolPrice: (symbol: string) => ['symbolPrice', symbol] as const,
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
  ownershipFlowNote: ['ownershipFlowNote'] as const,
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
  // Polymarket. Keyed by slug for the reason the news panel is keyed by news
  // id: a detail panel reads one key and never knows whether a fetch is in
  // flight, so a late response for a deselected market is physically unable to
  // render under the one now on screen.
  polymarketBoard: ['polymarketBoard'] as const,
  polymarketMarket: (slug: string) => ['polymarketMarket', slug] as const,
  polymarketMap: ['polymarketMap'] as const,
  polymarketAnalysis: (slug: string) => ['polymarketAnalysis', slug] as const,
  polymarketAnalysisJob: (jobId: string) => ['polymarketAnalysisJob', jobId] as const,
  polymarketOrigin: (slug: string) => ['polymarketOrigin', slug] as const,
  polymarketOriginJob: (jobId: string) => ['polymarketOriginJob', jobId] as const,
  // Borsa İstanbul. The hooks live in hooks/useBist.ts; the keys stay here for
  // the reason the social and polymarket blocks above give — one list to read
  // when invalidating across features.
  //
  // The screener keys carry their whole query object rather than a positional
  // list of filters. There are six of them and they are optional, so a
  // positional key would be six `?? null` slots that nobody could read at a
  // glance and that would silently collide the day a seventh is added.
  bistOverview: ['bistOverview'] as const,
  bistMarketNote: ['bistMarketNote'] as const,
  bistFundsMarketNote: (fundType: string) => ['bistFundsMarketNote', fundType] as const,
  bistStocks: (query: Record<string, unknown>) => ['bistStocks', query] as const,
  bistStock: (ticker: string, range: string) => ['bistStock', ticker, range] as const,
  bistHeatmap: (index: string, limit: number) => ['bistHeatmap', index, limit] as const,
  bistFunds: (query: Record<string, unknown>) => ['bistFunds', query] as const,
  bistFund: (code: string, months: number) => ['bistFund', code, months] as const,
  bistFundHoldings: (code: string) => ['bistFundHoldings', code] as const,
  bistFundComparison: (codes: string[], months: number) =>
    ['bistFundComparison', codes.join(','), months] as const,
  bistMacro: (fxRange: string) => ['bistMacro', fxRange] as const,
  bistMacroNote: ['bistMacroNote'] as const,
  bistKap: (query: Record<string, unknown>) => ['bistKap', query] as const,
  bistKapNote: (index: number) => ['bistKapNote', index] as const,
  bistRestrictions: (limit: number) => ['bistRestrictions', limit] as const,
  bistViop: (underlying?: string) => ['bistViop', underlying ?? null] as const,
  bistFinancials: (ticker: string, quarters: number) =>
    ['bistFinancials', ticker, quarters] as const,
  bistFinancialsNote: (ticker: string) => ['bistFinancialsNote', ticker] as const,
  bistViopMap: (ticker: string, sessions: number) => ['bistViopMap', ticker, sessions] as const,
  bistViopMapNote: (ticker: string, sessions: number) =>
    ['bistViopMapNote', ticker, sessions] as const,
  bistViopUnderlyings: ['bistViopUnderlyings'] as const,
  bistViopNote: ['bistViopNote'] as const,
  bistCalendar: (daysAhead: number, daysBack: number) =>
    ['bistCalendar', daysAhead, daysBack] as const,
  bistPositioning: (limit: number) => ['bistPositioning', limit] as const,
  bistPositioningNote: ['bistPositioningNote'] as const,
  bistNightShift: ['bistNightShift'] as const,
  bistOwnershipBoard: ['bistOwnershipBoard'] as const,
  bistOwnershipEntity: (entityId: string) => ['bistOwnershipEntity', entityId] as const,
  bistOwnershipMoves: (limit: number, ticker?: string) =>
    ['bistOwnershipMoves', limit, ticker ?? null] as const,
  bistAssetOwners: (ticker: string) => ['bistAssetOwners', ticker] as const,
  bistOwnershipNote: ['bistOwnershipNote'] as const,
  bistRadar: (horizon: string) => ['bistRadar', horizon] as const,
  bistRadarJob: (jobId: string) => ['bistRadarJob', jobId] as const,
  userSettings: ['userSettings'] as const,
};

// ==========================================
// HOME PAGE HOOKS
// ==========================================

/**
 * One symbol's daily read.
 *
 * Per symbol rather than one call for all three slots: swapping one asset then
 * costs one request instead of three, and a symbol the backend cannot resolve
 * fails inside its own card rather than emptying the strip. `retry: false`
 * because the failure this hook actually sees is a 404 for an unknown ticker,
 * and retrying that three times only delays the message.
 */
export function useAssetBrief(symbol: string | null) {
  return useQuery({
    queryKey: queryKeys.assetBrief(symbol ?? ''),
    queryFn: () => fetchAssetBrief(symbol as string),
    enabled: !!symbol,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    retry: false,
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
/**
 * Open interest per exchange against price.
 *
 * Same cadence as the liquidation views because it is backed by the same
 * upstreams and the same 120s server cache — polling harder would spend the
 * Coinalyze budget without changing a bar. `placeholderData` keeps the board
 * drawn while the user switches symbol or interval; a chart that blanks on
 * every toolbar click reads as a failure. The component renders its own error
 * state, so the global toast stays out of it.
 */
export function useOpenInterest(symbol: string, interval: string) {
  return useQuery({
    queryKey: queryKeys.openInterest(symbol, interval),
    queryFn: () => fetchOpenInterest(symbol, interval),
    staleTime: 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
    enabled: Boolean(symbol),
    placeholderData: (previous) => previous,
    meta: { silentError: true },
  });
}

export function useDexPerps() {
  return useQuery({
    queryKey: queryKeys.dexPerps(),
    queryFn: fetchDexPerps,
    // The backend caches for 120s; polling faster only re-serves its cache.
    staleTime: 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
    placeholderData: (previous) => previous,
    meta: { silentError: true },
  });
}

export function useLiquidationMap(
  symbol: string,
  interval: string,
  venue: LiquidationExchange = 'okx'
) {
  return useQuery({
    queryKey: queryKeys.liquidationMap(symbol, interval, venue),
    queryFn: () => fetchLiquidationMap(symbol, interval, undefined, venue),
    staleTime: 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
    enabled: Boolean(symbol),
    // The venues answer with the same shape at slightly different depths, so
    // holding the previous one keeps the chart up while the next arrives
    // instead of blanking the page on every switch.
    placeholderData: (previous) => previous,
  });
}

/**
 * The same model as `useLiquidationMap`, emitted as spans.
 *
 * Polled on the same gentle cadence and for the same reason. The leverage
 * filter deliberately does not enter the key — the payload already carries
 * every tier, so toggling a band is a client-side filter rather than a refetch.
 */
export function useLiquidationLines(
  symbol: string,
  interval: string,
  columns: number,
  venue: LiquidationExchange = 'okx'
) {
  return useQuery({
    queryKey: queryKeys.liquidationLines(symbol, interval, columns, venue),
    queryFn: () => fetchLiquidationLines(symbol, interval, columns, venue),
    staleTime: 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
    enabled: Boolean(symbol),
    placeholderData: (previous) => previous,
  });
}

/**
 * The standing liquidation book as a price profile.
 *
 * Same cadence as its two siblings, and for the same reason: the model replays
 * the whole window on a miss, and the answer moves at the speed of one candle.
 */
export function useLiquidationProfile(
  symbol: string,
  interval: string,
  columns: number,
  venue: LiquidationVenue
) {
  return useQuery({
    queryKey: queryKeys.liquidationProfile(symbol, interval, columns, venue),
    queryFn: () => fetchLiquidationProfile(symbol, interval, columns, venue),
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

const MACRO_REFRESH_MS = 120 * 1000;

/**
 * The cross-asset regime read.
 *
 * Two cadences in one hook. Settled, it tracks the board it is derived from at
 * 120s. While the sentence is being written it looks again every few seconds,
 * then stops — including when the note will never arrive, so a page left open
 * against a dead provider chain does not re-ask it forever.
 */
export function useMacroRegime() {
  return useQuery({
    queryKey: queryKeys.macroRegime,
    queryFn: fetchMacroRegime,
    staleTime: 60 * 1000,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? MACRO_REFRESH_MS : generating;
    },
  });
}

/**
 * The elections board.
 *
 * Five minutes against a server that caches the odds for fifteen and rebuilds
 * the calendar once a day by cron, so a tighter interval would only re-read the
 * same board — and the odds fetch behind it is a multi-megabyte Gamma payload.
 * Slower than the macro board beside it on purpose: an election calendar is not
 * a tape, and nothing on it changes between two ticks of a price panel.
 */
export function useElections() {
  return useQuery({
    queryKey: queryKeys.elections,
    queryFn: fetchElections,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });
}

/**
 * The Pentagon Pizza Index.
 *
 * Ten minutes, matching the server's own cache. The upstream samples roughly
 * hourly, so a tighter interval would only re-read the same snapshot — and this
 * payload is a full scrape behind the cache, which is not a page anyone should
 * be re-triggering on a fast loop.
 *
 * No `retry` override and no error branch in the consumers: the endpoint answers
 * 200 with `status: 'unavailable'` rather than failing, so an outage arrives as
 * data the panel renders rather than as a query error.
 */
export function usePizzaIndex() {
  return useQuery({
    queryKey: queryKeys.pizzaIndex,
    queryFn: fetchPizzaIndex,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });
}

/**
 * The Nothing Ever Happens Index, fetched only while its panel is open.
 *
 * The difference from the pizza hook beside it is where it is mounted. That one
 * feeds a reading rendered in the header on every page, so it has to be in
 * flight whether or not anyone looks; this one is called only from inside the
 * panel body, which exists only while the panel is open. Polling prediction
 * markets on every page load for a strip nobody has opened would be a
 * background request with no reader.
 *
 * Two minutes matches the server's cache, so a panel left open re-reads roughly
 * when there is something new to read.
 */
export function useNehIndex() {
  return useQuery({
    queryKey: queryKeys.nehIndex,
    queryFn: fetchNehIndex,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
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
// CHAINS PAGE HOOKS
// ==========================================

/**
 * The Chains board.
 *
 * Ten seconds, matching the server's own cache exactly — polling faster only
 * re-reads the same payload, and polling slower would leave the cache to expire
 * unused so that some unlucky request pays for eight chains' worth of fetching.
 *
 * That interval is not what makes the page feel live, and it is not trying to
 * be: the fastest chain here produces four blocks a second, which no poll can
 * chase. The cards animate against each block's own server timestamp between
 * refreshes, so the page keeps moving while this sits still.
 */
export function useChainsBoard() {
  return useQuery({
    queryKey: queryKeys.chainsBoard,
    queryFn: fetchChainsBoard,
    staleTime: 10 * 1000,
    refetchInterval: 10 * 1000,
  });
}

// Far slower than the board's ten seconds, deliberately. These readings are
// measured against days of history and an hour-long note; nothing about them can
// change six times a minute, and matching the board's cadence would only add
// requests that return the same payload.
const CHAIN_ANOMALY_REFRESH_MS = 60 * 1000;

/** What on the board is not normal, and the note explaining why. */
export function useChainAnomalies() {
  return useQuery({
    queryKey: queryKeys.chainAnomalies,
    queryFn: fetchChainAnomalies,
    staleTime: 30 * 1000,
    refetchInterval: (query) => {
      const generating = aiNotePollInterval(query.state.data?.note);
      return generating === false ? CHAIN_ANOMALY_REFRESH_MS : generating;
    },
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

/**
 * The signed-in user's watchlists.
 *
 * Gated on there being a user at all. Watchlists became per-user — they used to
 * be one shared file behind three unauthenticated endpoints — so a signed-out
 * visitor has none rather than everyone's, and firing the query anyway would
 * poll a 401 every thirty seconds.
 */
export function useWatchlists() {
  const { user } = useOptionalAuth();
  return useQuery({
    queryKey: [...queryKeys.watchlists, user?.id ?? 'anonymous'],
    queryFn: fetchWatchlists,
    enabled: !!user,
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
 * Last quarter's institutional flow, narrated.
 *
 * Keeps the no-polling rule above — 13F filings land quarterly, so there is
 * nothing to poll for — with one exception: while the sentence is being written,
 * it looks again every few seconds until the run settles either way.
 */
export function useOwnershipFlowNote() {
  return useQuery({
    queryKey: queryKeys.ownershipFlowNote,
    queryFn: fetchOwnershipFlowNote,
    staleTime: OWNERSHIP_STALE_TIME,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => aiNotePollInterval(query.state.data?.note),
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

// ===== POLYMARKET PAGE HOOKS =====

/**
 * The prediction-market board.
 *
 * Ten seconds, matching the chains board. Odds can move in a second, but the
 * server caches for fifteen and a client polling faster than the server
 * refreshes only spends requests re-reading the same payload.
 */
export function usePolymarketBoard() {
  return useQuery({
    queryKey: queryKeys.polymarketBoard,
    queryFn: fetchPolymarketBoard,
    staleTime: 10 * 1000,
    refetchInterval: 10 * 1000,
  });
}

/**
 * One market's facts and microstructure. No model is consulted server-side.
 *
 * `enabled` on the slug, so nothing is fetched until a market is actually
 * selected. Not silenced: this fires because the reader clicked something, and
 * a failure they caused is one they should be told about.
 */
export function usePolymarketMarket(slug: string | null) {
  return useQuery({
    queryKey: queryKeys.polymarketMarket(slug ?? 'none'),
    queryFn: () => fetchPolymarketMarket(slug as string),
    enabled: Boolean(slug),
    staleTime: 10 * 1000,
  });
}

/**
 * Kick off the bet analysis for one market.
 *
 * A run that ends in a refusal is a successful run: the pipeline declines when
 * the evidence it gathered does not support a judgement. Nothing here treats
 * that as an error.
 */
export function useStartPolymarketAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => startPolymarketAnalysis(slug),
    onSuccess: (job: PolymarketAnalysisJob) => {
      queryClient.setQueryData(queryKeys.polymarketAnalysisJob(job.jobId), job);
      // A finished job carries its verdict straight away — publishing it here
      // saves the panel a poll interval of looking like it is still working.
      if (job.result) {
        queryClient.setQueryData(queryKeys.polymarketAnalysis(job.slug), job.result);
      }
    },
  });
}

/**
 * Poll a running analysis, publishing the verdict under the market's own key.
 *
 * The panel reads `polymarketAnalysis(slug)` and never learns whether a job is
 * in flight. Because everything is keyed by slug, a verdict that arrives after
 * the reader has closed one market and opened another is physically unable to
 * render under the wrong question.
 */
export function usePolymarketAnalysisJob(jobId: string | undefined) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.polymarketAnalysisJob(jobId ?? ''),
    queryFn: async () => {
      const job = await fetchPolymarketAnalysisJob(jobId!);
      if (job.result) {
        queryClient.setQueryData(queryKeys.polymarketAnalysis(job.slug), job.result);
      }
      return job;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? JOB_POLL_INTERVAL_MS : false;
    },
    // An expired job is gone for good server-side; retrying only delays the error.
    retry: false,
    gcTime: 0,
  });
}

/** The verdict for a market, once a job has published one. */
export function usePolymarketAnalysis(slug: string | null) {
  return useQuery<PolymarketVerdict | null>({
    queryKey: queryKeys.polymarketAnalysis(slug ?? ''),
    queryFn: async () => null,
    enabled: Boolean(slug),
    staleTime: Infinity,
  });
}

/**
 * Kick off the "why was this bet opened" trace for one market.
 *
 * Started alongside the verdict by the same click, and deliberately not chained
 * to it. This run is the shorter of the two — three searches and one model call
 * against a sweep, two synthesis calls and an attribution pass — so making the
 * reader wait for the verdict to publish it would hide an answer that was ready
 * a minute earlier.
 */
export function useStartPolymarketOrigin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => startPolymarketOrigin(slug),
    onSuccess: (job: PolymarketOriginJob) => {
      queryClient.setQueryData(queryKeys.polymarketOriginJob(job.jobId), job);
      if (job.result) {
        queryClient.setQueryData(queryKeys.polymarketOrigin(job.slug), job.result);
      }
    },
  });
}

/** Poll a running origin trace, publishing the report under the market's key. */
export function usePolymarketOriginJob(jobId: string | undefined) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.polymarketOriginJob(jobId ?? ''),
    queryFn: async () => {
      const job = await fetchPolymarketOriginJob(jobId!);
      if (job.result) {
        queryClient.setQueryData(queryKeys.polymarketOrigin(job.slug), job.result);
      }
      return job;
    },
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? JOB_POLL_INTERVAL_MS : false;
    },
    retry: false,
    gcTime: 0,
  });
}

/** The origin report for a market, once a job has published one. */
export function usePolymarketOrigin(slug: string | null) {
  return useQuery<PolymarketOriginReport | null>({
    queryKey: queryKeys.polymarketOrigin(slug ?? ''),
    queryFn: async () => null,
    enabled: Boolean(slug),
    staleTime: Infinity,
  });
}

/**
 * The map's three layers.
 *
 * Five minutes, matching the server. The jurisdiction list moves about once a
 * year, the subject layer follows a board that refreshes on its own, and the
 * activity histogram is a shape rather than a number — none of them is improved
 * by a faster poll, and the trade tapes behind the third are the most expensive
 * fetch on this surface.
 */
export function usePolymarketMap() {
  return useQuery({
    queryKey: queryKeys.polymarketMap,
    queryFn: fetchPolymarketMap,
    staleTime: 5 * 60 * 1000,
  });
}
