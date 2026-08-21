import { NewsItem, SentimentAnalysis } from '@/store/useStore';
import { getSupabase } from '@/lib/supabase';
import { toChatJob, type ChatJob, type StoredChatStep } from '@/lib/chat-job';
import type { AiNote } from '@/lib/ai-note';

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API_BASE = API_BASE_URL;

/** Error thrown by {@link apiFetch} for non-2xx responses, carrying the status. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /**
     * The raw `detail` when the backend sent a structured one.
     *
     * Most endpoints answer with a plain string, which becomes `message` and
     * leaves this undefined. A few carry data the UI has to act on rather than
     * only display — `POST /api/social/conversations` returns the list of
     * unmet requirements — and that would be lost if the body were flattened
     * to a sentence. See `dmRefusalReasons`.
     */
    public detail?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * The machine-readable reasons behind a refused DM, if this error carries any.
 *
 * Returns an empty array for every other failure, so callers can render the
 * checklist without first testing what kind of error they were handed.
 */
export function dmRefusalReasons(error: unknown): string[] {
  if (!(error instanceof ApiError)) return [];
  const detail = error.detail;
  if (!detail || typeof detail !== 'object') return [];
  const reasons = (detail as { reasons?: unknown }).reasons;
  if (!Array.isArray(reasons)) return [];
  return reasons.filter((reason): reason is string => typeof reason === 'string');
}

type ApiFetchOptions = RequestInit & {
  params?: Record<string, string | number | boolean | undefined | null>;
  /** Skip attaching the Supabase access token (for public endpoints). */
  anonymous?: boolean;
};

/**
 * Current Supabase access token, or undefined when signed out.
 *
 * The backend runs with the service-role key and therefore enforces
 * authorization in its own auth dependency — every user-scoped route requires
 * this token. Resolved per request so a refreshed session is picked up.
 */
async function getAccessToken(): Promise<string | undefined> {
  if (typeof window === 'undefined') return undefined;
  try {
    const { data } = await getSupabase().auth.getSession();
    return data.session?.access_token;
  } catch {
    // Supabase not configured, or no session — treat as anonymous and let
    // the backend return 401 if the endpoint requires auth.
    return undefined;
  }
}

/**
 * Thin wrapper around fetch for the Oracle-X backend.
 * - Prepends the API base URL (unless an absolute URL is passed)
 * - Serialises `params` into the query string (skipping nullish values)
 * - Sets a JSON Content-Type only when a body is present
 * - Attaches the Supabase bearer token unless `anonymous` is set
 * - Throws {@link ApiError} on non-2xx responses
 * - Returns parsed JSON (or `undefined` for empty 204 responses)
 */
export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { params, headers, anonymous, ...init } = options;

  let url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  if (params) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') {
        search.append(key, String(value));
      }
    }
    const qs = search.toString();
    if (qs) url += `?${qs}`;
  }

  const finalHeaders: Record<string, string> = { ...(headers as Record<string, string>) };
  // FormData is excluded deliberately: the browser has to set the Content-Type
  // itself so it can append the multipart boundary. Naming it here would send a
  // boundary-less header and the server would fail to parse the upload.
  if (init.body && !(init.body instanceof FormData) && !finalHeaders['Content-Type']) {
    finalHeaders['Content-Type'] = 'application/json';
  }
  if (!anonymous && !finalHeaders['Authorization']) {
    const token = await getAccessToken();
    if (token) finalHeaders['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, { ...init, headers: finalHeaders });
  if (!response.ok) {
    // FastAPI puts the human-readable reason in `detail`. Discarding it and
    // reporting only the status turns every message the backend wrote for the
    // user — "This email is already registered", "Too many attempts" — into
    // "Request to /x failed: 409". Read the body once and prefer that text,
    // falling back to the status line when the body is empty or not JSON.
    //
    // `detail` is usually that string. When it is an object it carries data the
    // caller has to act on — the DM gate returns which requirements are unmet —
    // so the object is kept whole on the error and its `message` field, if any,
    // becomes the displayed text.
    const raw = await response
      .json()
      .then((body: unknown) =>
        body && typeof body === 'object' ? (body as { detail?: unknown }).detail : undefined
      )
      .catch(() => undefined);

    let message: string | undefined;
    let structured: unknown;
    if (typeof raw === 'string') {
      message = raw;
    } else if (raw && typeof raw === 'object') {
      structured = raw;
      const inner = (raw as { message?: unknown }).message;
      if (typeof inner === 'string') message = inner;
    }

    throw new ApiError(
      response.status,
      message ?? `Request to ${path} failed: ${response.status}`,
      structured
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function fetchNews(assetType?: string): Promise<NewsItem[]> {
  const data = await apiFetch<{ items: NewsItem[] }>('/api/news', {
    params: { asset_type: assetType },
  });
  return data.items;
}

// The blocking `POST /api/analyze` client is gone: the panel now starts a job
// and polls it, which reports progress instead of holding a connection open for
// the whole pipeline. The endpoint itself is kept server-side for other clients.

// ==========================================
// NEWS ANALYSIS (job-driven research note)
// ==========================================

export type NewsAnalysisJobStatus = 'queued' | 'running' | 'done' | 'error';

export interface NewsAnalysisStage {
  key: string;
  label: string;
}

export interface EvidenceItem {
  claim: string;
  /** Verbatim from the source article; absent when the point came from market data. */
  quote?: string;
  direction: 'bullish' | 'bearish' | 'neutral';
  weight: 'primary' | 'supporting' | 'context';
}

export interface PrecedentAnalogy {
  title: string;
  date?: string;
  symbol?: string;
  similarity: number;
  outcome?: string;
  priceChange?: number;
  apparentSentiment?: string;
  durableDirection?: string;
  horizons: Record<string, number>;
  maxDrawdownPct?: number;
  maxRunupPct?: number;
  /** The market did the opposite of what the headline implied. */
  surprised: boolean;
  inverted: boolean;
  source: string;
}

export interface Citation {
  label: string;
  url: string;
  kind: string;
}

export interface DataCoverage {
  articleText: 'full' | 'summary-only' | 'unavailable';
  articleChars: number;
  unavailable: string[];
}

export interface NewsAnalysis extends SentimentAnalysis {
  keyFactors: string[];
  priceImpact?: string;
  riskLevel?: string;
  timeHorizon?: string;
  materiality?: string;
  mechanism?: string;
  invalidation?: string;
  regimeNote?: string;
  evidence: EvidenceItem[];
  precedents: PrecedentAnalogy[];
  citations: Citation[];
  coverage: DataCoverage;
  analysedAt?: string;
  durationSeconds?: number;
  model?: string;
  stagesRun: string[];
}

export interface NewsAnalysisJob {
  jobId: string;
  newsId: string;
  status: NewsAnalysisJobStatus;
  stage?: string;
  stageIndex: number;
  stages: NewsAnalysisStage[];
  elapsedSeconds: number;
  result?: NewsAnalysis;
  /** Published before the job finishes when a verdict is usable early. */
  partialResult?: NewsAnalysis;
  error?: string;
}

interface RawEvidenceItem {
  claim: string;
  quote: string | null;
  direction: EvidenceItem['direction'];
  weight: EvidenceItem['weight'];
}

interface RawPrecedent {
  title: string;
  date: string | null;
  symbol: string | null;
  similarity: number;
  outcome: string | null;
  price_change: number | null;
  apparent_sentiment: string | null;
  durable_direction: string | null;
  horizons: Record<string, number>;
  max_drawdown_pct: number | null;
  max_runup_pct: number | null;
  surprised: boolean;
  inverted: boolean;
  source: string;
}

interface RawNewsAnalysis {
  sentiment: string;
  confidence: number;
  reasoning: string;
  historical_context: string;
  technical_signals: SentimentAnalysis['technical_signals'];
  prediction_hash?: string | null;
  tx_hash?: string | null;
  source?: string | null;
  key_factors: string[];
  price_impact: string | null;
  risk_level: string | null;
  time_horizon: string | null;
  materiality: string | null;
  mechanism: string | null;
  invalidation: string | null;
  regime_note: string | null;
  evidence: RawEvidenceItem[];
  precedents: RawPrecedent[];
  citations: Citation[];
  coverage: {
    article_text: DataCoverage['articleText'];
    article_chars: number;
    unavailable: string[];
  };
  analysed_at: string | null;
  duration_seconds: number | null;
  model: string | null;
  stages_run: string[];
}

interface RawNewsAnalysisJob {
  job_id: string;
  key: string;
  status: NewsAnalysisJobStatus;
  stage: string | null;
  stage_index: number;
  stages: NewsAnalysisStage[];
  elapsed_seconds: number;
  result: RawNewsAnalysis | null;
  partial_result: RawNewsAnalysis | null;
  error: string | null;
}

function toNewsAnalysis(raw: RawNewsAnalysis): NewsAnalysis {
  return {
    sentiment: raw.sentiment as SentimentAnalysis['sentiment'],
    confidence: raw.confidence,
    reasoning: raw.reasoning,
    historical_context: raw.historical_context,
    technical_signals: raw.technical_signals,
    prediction_hash: raw.prediction_hash ?? undefined,
    tx_hash: raw.tx_hash ?? undefined,
    source: raw.source ?? undefined,
    keyFactors: raw.key_factors ?? [],
    priceImpact: raw.price_impact ?? undefined,
    riskLevel: raw.risk_level ?? undefined,
    timeHorizon: raw.time_horizon ?? undefined,
    materiality: raw.materiality ?? undefined,
    mechanism: raw.mechanism ?? undefined,
    invalidation: raw.invalidation ?? undefined,
    regimeNote: raw.regime_note ?? undefined,
    evidence: (raw.evidence ?? []).map((e) => ({
      claim: e.claim,
      quote: e.quote ?? undefined,
      direction: e.direction,
      weight: e.weight,
    })),
    precedents: (raw.precedents ?? []).map((p) => ({
      title: p.title,
      date: p.date ?? undefined,
      symbol: p.symbol ?? undefined,
      similarity: p.similarity,
      outcome: p.outcome ?? undefined,
      priceChange: p.price_change ?? undefined,
      apparentSentiment: p.apparent_sentiment ?? undefined,
      durableDirection: p.durable_direction ?? undefined,
      horizons: p.horizons ?? {},
      maxDrawdownPct: p.max_drawdown_pct ?? undefined,
      maxRunupPct: p.max_runup_pct ?? undefined,
      surprised: p.surprised,
      inverted: p.inverted,
      source: p.source,
    })),
    citations: raw.citations ?? [],
    coverage: {
      articleText: raw.coverage?.article_text ?? 'unavailable',
      articleChars: raw.coverage?.article_chars ?? 0,
      unavailable: raw.coverage?.unavailable ?? [],
    },
    analysedAt: raw.analysed_at ?? undefined,
    durationSeconds: raw.duration_seconds ?? undefined,
    model: raw.model ?? undefined,
    stagesRun: raw.stages_run ?? [],
  };
}

function toNewsJob(raw: RawNewsAnalysisJob): NewsAnalysisJob {
  return {
    jobId: raw.job_id,
    newsId: raw.key,
    status: raw.status,
    stage: raw.stage ?? undefined,
    stageIndex: raw.stage_index,
    stages: raw.stages ?? [],
    elapsedSeconds: raw.elapsed_seconds,
    result: raw.result ? toNewsAnalysis(raw.result) : undefined,
    partialResult: raw.partial_result ? toNewsAnalysis(raw.partial_result) : undefined,
    error: raw.error ?? undefined,
  };
}

/**
 * Start the research note for a news item.
 *
 * The backend single-flights on the news id, so a second click while one is
 * running re-attaches to it rather than spawning a second pipeline.
 */
export async function startNewsAnalysisJob(
  newsId: string,
  currentPrice?: number
): Promise<NewsAnalysisJob> {
  const query =
    currentPrice !== undefined && currentPrice > 0 ? `?current_price=${currentPrice}` : '';
  return toNewsJob(
    await apiFetch<RawNewsAnalysisJob>(
      `/api/news/${encodeURIComponent(newsId)}/analysis/jobs${query}`,
      { method: 'POST' }
    )
  );
}

export async function fetchNewsAnalysisJob(jobId: string): Promise<NewsAnalysisJob> {
  return toNewsJob(
    await apiFetch<RawNewsAnalysisJob>(`/api/news/analysis/jobs/${encodeURIComponent(jobId)}`)
  );
}

/**
 * The stored note for this item, or null when none has been produced yet.
 *
 * "Nobody has analysed this item" is the normal state on a first click, so the
 * backend answers it with a null body rather than a 404. The 404 kept the
 * ordinary case flowing through the global query-error handler, which raised a
 * connection-error toast every time a headline was opened. The 404 branch stays
 * for older backends that still return one.
 */
export async function fetchCachedNewsAnalysis(newsId: string): Promise<NewsAnalysis | null> {
  try {
    const raw = await apiFetch<RawNewsAnalysis | null>(
      `/api/news/${encodeURIComponent(newsId)}/analysis`
    );
    return raw ? toNewsAnalysis(raw) : null;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function verifyOnChain(_predictionHash: string): Promise<{ txHash: string }> {
  // On-chain doğrulama henüz uygulanmadı — Faz 3'te smart contract entegrasyonu ile aktif edilecek.
  throw new Error('On-chain verification is not yet implemented. Coming in Phase 3.');
}

/**
 * Fetch the current price for a symbol, crypto or equity.
 *
 * Goes through the backend rather than calling an exchange from the page: the
 * browser used to hit Binance directly, which fails on every network where
 * Binance is blocked and gave the page no way to fall back to another venue.
 *
 * @param symbol - TradingView format symbol (e.g., "BINANCE:BTCUSDT"), or
 *   `undefined` for a news item that was not attributed to any asset.
 * @returns The price, or null when none could be resolved.
 */
// Fear & Greed Index types
export interface FearGreedHistory {
  value: number;
  classification: string;
  date: string;
}

export interface FearGreedData {
  value: number;
  classification: string;
  timestamp: string;
  history: FearGreedHistory[];
}

// Market Overview types.
// One row of the overview table, for a coin or a stock. The optional fields
// are the ones only one of the two sources reports: CoinGecko carries
// change_7d/sparkline, the NASDAQ screener carries sector and the 52-week
// range.
//
// change_7d is null when unreported rather than 0, because 0 is a real
// reading a stablecoin posts every day — `--` and `+0.00%` mean different
// things.
export interface CoinData {
  symbol: string;
  name: string;
  logo: string;
  price: number;
  change_24h: number;
  change_7d?: number | null;
  sparkline?: number[];
  volume_24h: number;
  high_24h: number;
  low_24h: number;
  market_cap: number;
  market_cap_rank: number;
  sector?: string;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
}

export interface MarketStatus {
  status: string;
  message: string;
  color: string;
  next_event: string;
}

export interface MarketOverview {
  coins: CoinData[];
  total_volume_24h: number;
  total_market_cap: number;
  btc_dominance: number;
  eth_dominance?: number;
  active_cryptocurrencies: number;
  fear_greed: FearGreedData;
  timestamp: string;
  market_status?: MarketStatus;
}

export async function fetchFearGreedIndex(): Promise<FearGreedData> {
  return apiFetch<FearGreedData>('/api/fear-greed');
}

export async function fetchMarketOverview(): Promise<MarketOverview> {
  return apiFetch<MarketOverview>('/api/market-overview');
}

export interface NasdaqOverview {
  coins: CoinData[]; // Reusing CoinData for compatibility
  total_volume_24h: number;
  total_market_cap: number;
  btc_dominance: number; // N/A for stocks
  active_cryptocurrencies: number;
  fear_greed?: {
    value: number;
    classification: string;
    timestamp: string;
  };
  timestamp: string;
}

export async function fetchNasdaqOverview(): Promise<NasdaqOverview> {
  return apiFetch<NasdaqOverview>('/api/nasdaq-overview');
}

// ==========================================
// HOME PAGE TYPES & API
// ==========================================

// A `null` on any of these numeric fields means the backend could not measure the
// value, not that it measured zero. Render those as "—", never as 0.
export interface FundingRate {
  symbol: string;
  rate: number;
  rate_formatted: string;
  index_price: number | null;
  mark_price: number | null;
  next_funding_time: number;
  /** Settlement period. OKX runs both 4h and 8h perpetuals, so this varies by row. */
  interval_hours: number;
  /** Rate cleared the backend's outlier threshold — the row carries a badge. */
  is_extreme: boolean;
}

export interface Liquidation {
  symbol: string;
  side: 'Long' | 'Short';
  price: number;
  amount_usd: number;
  time_ago: string;
  timestamp: number;
}

export interface MacroEvent {
  title: string;
  country: string;
  date: string;
  time: string;
  impact: 'Low' | 'Medium' | 'High';
  forecast: string;
  previous: string;
}

export interface OnChainData {
  active_addresses: {
    btc: number | null;
    eth: number | null;
    btc_change_24h: number | null;
    eth_change_24h: number | null;
  };
  transactions_24h: {
    btc: number | null;
    eth: number | null;
  };
  network_load: {
    eth_gas_gwei: number | null;
    btc_mempool_size_vbytes: number | null;
  };
  /** Real exchange in/out flows from Coin Metrics. Positive = net inflow. */
  exchange_flows: {
    btc_net_flow_usd: number | null;
    eth_net_flow_usd: number | null;
    /** UTC day the flows describe (YYYY-MM-DD); they settle a day behind. */
    as_of: string | null;
  };
  /** When the server built this payload. */
  as_of: string;
  /** True when the payload is being replayed from cache after an upstream failure. */
  stale: boolean;
}

export async function fetchFundingRates(): Promise<FundingRate[]> {
  return apiFetch<FundingRate[]>('/api/home/funding-rates');
}

// Deliberately unguarded: swallowing the error into [] rendered a backend outage
// as the claim "no major events this week". Let the caller show an error state.
export async function fetchMacroCalendar(): Promise<MacroEvent[]> {
  return apiFetch<MacroEvent[]>('/api/home/macro-calendar');
}

export async function fetchLiquidations(): Promise<Liquidation[]> {
  return apiFetch<Liquidation[]>('/api/home/liquidations');
}

export async function fetchOnChainData(): Promise<OnChainData> {
  return apiFetch<OnChainData>('/api/home/onchain');
}

// ==========================================
// MACRO BOARD
// ==========================================

/** Commodity groups the board renders, in the order they are shown. */
export type CommodityGroup = 'metals' | 'energy' | 'agriculture';

/** Whether a region's primary cash session is running. `unknown` = not determined. */
export interface MarketSessionStatus {
  status: 'open' | 'closed' | 'unknown';
  label: string;
}

/**
 * One board row. Every reading is nullable because a symbol no upstream answered
 * for keeps its row — the board must not silently shrink — and the page renders
 * those as an em dash rather than a zero.
 */
export interface MacroQuote {
  symbol: string;
  name: string;
  price: number | null;
  change_24h: number | null;
  /** Derived from the sparkline itself, so the number and the line always agree. */
  change_7d: number | null;
  high_52w: number | null;
  low_52w: number | null;
  currency: string | null;
  sparkline: number[];
  /** Which rung produced the quote: `yahoo`, `investing`, or null when neither did. */
  source: string | null;
}

export interface MacroCommodity extends MacroQuote {
  group: CommodityGroup;
  /** The unit the quote arrives in — grains and softs are US cents, not dollars. */
  unit: string;
}

export interface MacroIndex extends MacroQuote {
  region: string;
  market_status: MarketSessionStatus;
}

export interface MacroRatio {
  key: string;
  label: string;
  value: number | null;
  /** How many decimals the value is meaningful to; these ratios do not share a scale. */
  decimals: number;
  caption: string;
}

export interface MacroBoard {
  commodities: MacroCommodity[];
  indices: MacroIndex[];
  ratios: MacroRatio[];
  /** When the server built this payload. */
  as_of: string;
  /** True when the payload is being replayed from cache after an upstream failure. */
  stale: boolean;
}

export async function fetchMacroBoard(): Promise<MacroBoard> {
  return apiFetch<MacroBoard>('/api/macro/board');
}

/** One of the three votes behind the regime label. `signal` is -1, 0 or +1. */
export interface MacroRegimeComponent {
  key: string;
  label: string;
  signal: number;
  /**
   * The figure, already rounded to the grain its vote was decided on. The note
   * is written from these strings, so a cached sentence can never quote a number
   * that has since moved.
   */
  reading: string;
}

/**
 * The cross-asset read, and the sentence explaining it.
 *
 * `label` and `score` are computed on the server and are always present, so the
 * card renders whether or not `note` ever arrives. `not_measured` is not
 * decoration: this board carries no rates, credit or volatility feed, and a read
 * that does not say so overclaims.
 */
export interface MacroRegime {
  label: string;
  score: number;
  components: MacroRegimeComponent[];
  /** Components whose inputs were missing. Two or more and `label` is 'Unavailable'. */
  unavailable: string[];
  not_measured: string[];
  /** Set when the index readings span sessions that are not all open. */
  session_caveat: string | null;
  context: string[];
  stale: boolean;
  as_of: string;
  note: AiNote;
}

export async function fetchMacroRegime(): Promise<MacroRegime> {
  return apiFetch<MacroRegime>('/api/macro/regime', { anonymous: true });
}

// ==========================================
// PENTAGON PIZZA INDEX
// ==========================================

/**
 * `insufficient_data` and `unavailable` both arrive with a null index and mean
 * different things: the venues were shut, versus the source could not be read.
 * The UI branches on this rather than on `index === null` so those two never
 * collapse into one message.
 */
export type PizzaIndexStatus =
  | 'quiet'
  | 'normal'
  | 'elevated'
  | 'spike'
  | 'insufficient_data'
  | 'unavailable';

/** One pizzeria near the Pentagon: our reading, and the source's own beside it. */
export interface PizzaVenue {
  place_id: string;
  name: string;
  address: string | null;
  /** Live Google busyness, 0–100. Null when the venue is closed or silent. */
  current: number | null;
  /** The venue's usual busyness for this local weekday and hour. */
  baseline: number | null;
  /** `current / baseline`, clamped server-side. Null when not meaningful. */
  ratio: number | null;
  is_closed: boolean;
  /** Why this venue did not contribute, so a blank row can explain itself. */
  excluded_reason: string | null;
  /** The source's own derived figures. Where these and `ratio` disagree, that is the signal. */
  source_pct_of_usual: number | null;
  source_is_spike: boolean;
  source_spike_magnitude: number | null;
  freshness: string | null;
  /** This venue's own 24h, on the same hour grid as `PizzaIndex.history`. */
  history: PizzaVenueHour[];
}

export interface PizzaVenueHour {
  /** Matches a `PizzaIndexHour.hour_et` one-for-one, so the rows stack. */
  hour_et: string;
  /** Null where this venue reported nothing that hour — the slot stays empty. */
  ratio: number | null;
}

/** One hour of the trend, scored by the same rules as the headline reading. */
export interface PizzaIndexHour {
  /** Local (America/New_York) hour the bucket covers, truncated to :00. */
  hour_et: string;
  /** Null where too few venues reported that hour — the slot is kept, not closed. */
  index: number | null;
  venues_used: number;
}

/**
 * The Pentagon Pizza Index.
 *
 * `index` is a multiple of usual busyness, not a 0–100 score, and the UI renders
 * it that way on purpose — see `lib/pizza-index.ts`.
 */
export interface PizzaIndex {
  index: number | null;
  status: PizzaIndexStatus;
  label: string;
  venues_used: number;
  venues_total: number;
  venues: PizzaVenue[];
  history: PizzaIndexHour[];
  as_of: string;
  /** True when replayed from cache after the source could not be reached. */
  stale: boolean;
  source: string;
  source_url: string;
}

/**
 * Unlike the two macro endpoints above, this one never answers 503 — a failed
 * scrape of a novelty gauge must not surface as a page-level error, so the
 * failure arrives as `status: 'unavailable'` in an otherwise normal payload.
 */
export async function fetchPizzaIndex(): Promise<PizzaIndex> {
  return apiFetch<PizzaIndex>('/api/macro/pizza-index', { anonymous: true });
}

/**
 * The band the reading fell in. `unavailable` is the source having failed, and
 * is a status rather than a null index for the same reason the pizza gauge's is:
 * the panel needs a state to render, not an absence to explain.
 */
export type NehIndexStatus = 'calm' | 'watch' | 'happening' | 'happened' | 'unavailable';

/** The single tracked market currently setting the index. */
export interface NehTopMarket {
  slug: string | null;
  label: string | null;
  region: string | null;
  /** Polymarket's price for the Yes share, 0–1. */
  probability: number;
}

/**
 * The Nothing Ever Happens Index.
 *
 * `index` is the highest tracked probability in percent, not an average of the
 * basket — see `services/neh_index_service.py` for why the maximum is the
 * reading and the mean would be a permanently flat number.
 */
export interface NehIndex {
  index: number | null;
  status: NehIndexStatus;
  label: string;
  top: NehTopMarket | null;
  markets_tracked: number;
  as_of: string;
  /** True when replayed from cache after the source could not be reached. */
  stale: boolean;
  source: string;
  source_url: string;
}

/** Never answers 503, for the reason `fetchPizzaIndex` does not. */
export async function fetchNehIndex(): Promise<NehIndex> {
  return apiFetch<NehIndex>('/api/macro/neh-index', { anonymous: true });
}

// ==========================================
// LIQUIDATION MAP
// ==========================================

export interface LiquidationCandle {
  time: number; // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  volume_usd: number;
}

/** One heatmap cell: `[column, priceBin, longUsd, shortUsd]`. */
export type LiquidationCell = [number, number, number, number];

/**
 * A modelled liquidation heatmap — estimated levels at which leveraged
 * positions would be force-closed, not liquidations that actually happened.
 */
export interface LiquidationMap {
  symbol: string;
  interval: string;
  candles: LiquidationCandle[];
  cells: LiquidationCell[];
  bins: number;
  price_min: number;
  price_max: number;
  bin_size: number;
  max_value: number;
  interval_ms: number;
  leverage_tiers: number[];
  /**
   * Index of the first column backed by OKX open-interest and long/short data.
   * Columns before it are modelled from volume alone with a neutral split;
   * `0` means the whole window is covered.
   */
  stats_from_column: number;
}

export async function fetchLiquidationMap(
  symbol: string,
  interval: string,
  columns = 160,
  // The grid now spans a full leverage distance past the traded range, so it
  // needs more rows to keep each cell at roughly the previous price height.
  bins = 120
): Promise<LiquidationMap> {
  return apiFetch<LiquidationMap>(`/api/liquidations/map/${encodeURIComponent(symbol)}`, {
    params: { interval, columns, bins },
    anonymous: true,
  });
}

// ==========================================
// HEATMAP BOARD
// ==========================================

/**
 * One tile on the heatmap board.
 *
 * Nearly every metric is optional, and that is deliberate. The board colours a
 * non-negative move as a gain, so a missing 24h change reported as `0` renders
 * as a green "+0.00%" tile — a confident claim assembled out of an absence.
 * `undefined` means "not known" and the UI draws it as an explicit no-data
 * state, visually distinct from a low value.
 */
export interface HeatmapCoin {
  id: string;
  symbol: string;
  name: string;
  image: string;
  /**
   * `undefined` while the classification is still unresolved; `'Other'` once it
   * has been resolved and matched nothing. Collapsing the two is what made the
   * sector view unreadable.
   */
  sector?: string;
  /** `'stablecoin' | 'wrapped'` for assets that track another price. */
  peg_type?: string;
  price?: number;
  market_cap: number;
  volume_24h?: number;
  price_change_24h?: number;
  price_change_7d?: number;
  /** 0-100, log-scaled against absolute dollar volume ($1M → 0, $100B → 100). */
  volume_score?: number;
  turnover_pct?: number;
  developer_score?: number;
}

export interface HeatmapSector {
  sector: string;
  coin_count: number;
  market_cap: number;
  /** Market-cap weighted — the honest figure. */
  weighted_change_24h?: number;
  weighted_change_7d?: number;
  /** Plain mean, kept for the generated report's legacy column. */
  avg_change_24h?: number;
  /** 0-1: the share of this sector's coins that actually had a reading. */
  coverage: number;
  coins: HeatmapCoin[];
}

export interface HeatmapData {
  coins: HeatmapCoin[];
  sectors: HeatmapSector[];
  total_market_cap: number;
  weighted_change_24h?: number;
  weighted_change_7d?: number;
  /** Pegged assets filtered out of this board. */
  excluded_pegged: number;
  /** Coins still waiting on their first successful classification. */
  unresolved_count: number;
  timestamp: string;
  /** True when this is the last known good board after a failed refresh. */
  stale: boolean;
  age_seconds?: number;
}

/** FastAPI serialises absent optionals as `null`; the app only speaks `undefined`. */
function undef<T>(value: T | null | undefined): T | undefined {
  return value ?? undefined;
}

function normaliseHeatmapCoin(coin: HeatmapCoin): HeatmapCoin {
  return {
    ...coin,
    sector: undef(coin.sector),
    peg_type: undef(coin.peg_type),
    price: undef(coin.price),
    volume_24h: undef(coin.volume_24h),
    price_change_24h: undef(coin.price_change_24h),
    price_change_7d: undef(coin.price_change_7d),
    volume_score: undef(coin.volume_score),
    turnover_pct: undef(coin.turnover_pct),
    developer_score: undef(coin.developer_score),
  };
}

/**
 * The heatmap board.
 *
 * Answers 503 when the data genuinely cannot be produced, rather than an empty
 * board with a 200 — a blank grid is indistinguishable from a market where
 * nothing is listed. A board recovered from cache after a failed refresh comes
 * back as a normal 200 carrying `stale` and `age_seconds`.
 */
export async function fetchHeatmapData(limit = 50, includePegged = false): Promise<HeatmapData> {
  const data = await apiFetch<HeatmapData>('/api/heatmap/data', {
    params: { limit, include_pegged: includePegged },
    anonymous: true,
  });
  return {
    ...data,
    coins: data.coins.map(normaliseHeatmapCoin),
    sectors: data.sectors.map((sector) => ({
      ...sector,
      weighted_change_24h: undef(sector.weighted_change_24h),
      weighted_change_7d: undef(sector.weighted_change_7d),
      avg_change_24h: undef(sector.avg_change_24h),
      coins: sector.coins.map(normaliseHeatmapCoin),
    })),
    weighted_change_24h: undef(data.weighted_change_24h),
    weighted_change_7d: undef(data.weighted_change_7d),
    age_seconds: undef(data.age_seconds),
  };
}

// ==========================================
// WATCHLIST
// ==========================================

export interface WatchlistItem {
  symbol: string;
  type: 'STOCK' | 'CRYPTO';
  /** null when no quote resolved for this symbol — not a $0.00 price. */
  price: number | null;
  change_24h: number | null;
  logo?: string;
  name?: string;
}

export interface Watchlist {
  id: string;
  name: string;
  items: WatchlistItem[];
}

// Also unguarded — an [] here read as "you have no watchlists" and offered to
// create one, when in fact the request had failed.
export async function fetchWatchlists(): Promise<Watchlist[]> {
  return apiFetch<Watchlist[]>('/api/home/watchlist');
}

export async function createWatchlist(
  name: string,
  items: { symbol: string; type: 'STOCK' | 'CRYPTO' }[]
): Promise<Watchlist[]> {
  try {
    return await apiFetch<Watchlist[]>('/api/home/watchlist', {
      method: 'POST',
      body: JSON.stringify({ name, items }),
    });
  } catch (error) {
    console.error('Error creating watchlist:', error);
    throw error;
  }
}

export async function deleteWatchlist(id: string): Promise<void> {
  await apiFetch<void>(`/api/home/watchlist/${id}`, { method: 'DELETE' });
}

// ==========================================
// ASSET DETAIL
// ==========================================

export interface AssetDetail {
  type: 'crypto' | 'stock';
  symbol: string;
  name: string;
  logo: string;
  description: string;

  // Crypto-specific
  categories?: string[];
  genesis_date?: string;
  hashing_algorithm?: string;
  circulating_supply?: number;
  total_supply?: number;
  max_supply?: number | null;
  ath?: number;
  ath_change_percentage?: number;
  ath_date?: string;
  atl?: number;
  atl_change_percentage?: number;
  atl_date?: string;
  fully_diluted_valuation?: number;
  // Crypto community
  twitter_followers?: number;
  reddit_subscribers?: number;
  telegram_channel_user_count?: number;
  // Crypto developer
  github_stars?: number;
  github_forks?: number;
  github_subscribers?: number;
  github_total_issues?: number;
  github_closed_issues?: number;
  github_pull_requests_merged?: number;
  commit_count_4_weeks?: number;
  // Crypto sentiment
  sentiment_votes_up_percentage?: number;
  sentiment_votes_down_percentage?: number;
  watchlist_portfolio_users?: number;

  // Stock-specific
  sector?: string;
  industry?: string;
  country?: string;
  employees?: number;
  website?: string;
  pe_ratio?: number | null;
  dividend_yield?: number | null;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
  // Stock financials
  revenue?: number | null;
  net_income?: number | null;
  earnings_per_share?: number | null;
  forward_eps?: number | null;
  forward_pe?: number | null;
  profit_margin?: number | null;
  operating_margin?: number | null;
  beta?: number | null;
  book_value?: number | null;
  price_to_book?: number | null;
  free_cash_flow?: number | null;
  debt_to_equity?: number | null;
  return_on_equity?: number | null;
  // Analyst
  target_high_price?: number | null;
  target_low_price?: number | null;
  target_mean_price?: number | null;
  recommendation?: string;
  // Moving averages
  fifty_day_average?: number | null;
  two_hundred_day_average?: number | null;

  // Common market data
  market_cap_rank?: number;
  price: number;
  market_cap: number;
  total_volume: number;
  change_24h: number;
  change_7d?: number;
  change_30d?: number;
  change_1y?: number;
  high_24h: number;
  low_24h: number;

  links: Record<string, string>;
  timestamp: string;
}

export async function fetchAssetDetail(
  symbol: string,
  type: 'crypto' | 'stock' = 'crypto'
): Promise<AssetDetail> {
  return apiFetch<AssetDetail>(`/api/asset-detail/${symbol}`, { params: { type } });
}

// ==========================================
// ANALYSIS REPORTS & NOTES
// ==========================================

export type TimeFrame = 'daily' | 'weekly' | 'monthly';

export const TIME_FRAMES: TimeFrame[] = ['daily', 'weekly', 'monthly'];

export interface AnalysisReport {
  /** Undefined until a report has been generated for this timeframe. */
  content?: string;
  timestamp?: string;
  timeframe: TimeFrame;
  /** Data feeds that were down when the report ran, named for the reader. */
  unavailable?: string[];
  durationSeconds?: number;
  stale: boolean;
}

/** Freshness metadata for one timeframe — drives the picker cards. */
export interface ReportSummary {
  timeframe: TimeFrame;
  generatedAt?: string;
  ageSeconds?: number;
  stale: boolean;
  unavailable: string[];
}

export type AnalysisJobStatus = 'queued' | 'running' | 'done' | 'error';

export interface AnalysisStage {
  key: string;
  label: string;
}

export interface AnalysisJob {
  jobId: string;
  timeframe: TimeFrame;
  status: AnalysisJobStatus;
  stage?: string;
  stageIndex: number;
  stages: AnalysisStage[];
  elapsedSeconds: number;
  result?: AnalysisReport;
  error?: string;
}

export interface Note {
  id: string;
  title: string;
  content: string;
  date: string;
}

/** The backend speaks snake_case; the UI speaks camelCase. */
interface RawAnalysisReport {
  content: string | null;
  timestamp: string | null;
  timeframe: TimeFrame;
  unavailable?: string[];
  duration_seconds?: number | null;
  stale: boolean;
}

interface RawReportSummary {
  timeframe: TimeFrame;
  generated_at: string | null;
  age_seconds: number | null;
  stale: boolean;
  unavailable: string[];
}

interface RawAnalysisJob {
  job_id: string;
  timeframe: TimeFrame;
  status: AnalysisJobStatus;
  stage: string | null;
  stage_index: number;
  stages: AnalysisStage[];
  elapsed_seconds: number;
  result: RawAnalysisReport | null;
  error: string | null;
}

function toReport(raw: RawAnalysisReport): AnalysisReport {
  return {
    content: raw.content ?? undefined,
    timestamp: raw.timestamp ?? undefined,
    timeframe: raw.timeframe,
    unavailable: raw.unavailable ?? [],
    durationSeconds: raw.duration_seconds ?? undefined,
    stale: raw.stale,
  };
}

export async function fetchAnalysisReport(timeframe: TimeFrame): Promise<AnalysisReport> {
  return toReport(await apiFetch<RawAnalysisReport>(`/api/analysis/report/${timeframe}`));
}

/**
 * Freshness of every stored report. Read-only and cheap — safe to call on
 * mount, unlike report generation, which is explicitly job-driven.
 */
export async function fetchReportSummaries(): Promise<Record<TimeFrame, ReportSummary>> {
  const raw = await apiFetch<Record<TimeFrame, RawReportSummary>>('/api/analysis/reports');
  const out = {} as Record<TimeFrame, ReportSummary>;
  for (const timeframe of TIME_FRAMES) {
    const entry = raw[timeframe];
    out[timeframe] = {
      timeframe,
      generatedAt: entry?.generated_at ?? undefined,
      ageSeconds: entry?.age_seconds ?? undefined,
      stale: entry?.stale ?? true,
      unavailable: entry?.unavailable ?? [],
    };
  }
  return out;
}

function toJob(raw: RawAnalysisJob): AnalysisJob {
  return {
    jobId: raw.job_id,
    timeframe: raw.timeframe,
    status: raw.status,
    stage: raw.stage ?? undefined,
    stageIndex: raw.stage_index,
    stages: raw.stages,
    elapsedSeconds: raw.elapsed_seconds,
    result: raw.result ? toReport(raw.result) : undefined,
    error: raw.error ?? undefined,
  };
}

/** Start report generation. Joins an in-flight run for the same timeframe. */
export async function startAnalysisJob(timeframe: TimeFrame): Promise<AnalysisJob> {
  return toJob(
    await apiFetch<RawAnalysisJob>(`/api/analysis/jobs/${timeframe}`, { method: 'POST' })
  );
}

export async function fetchAnalysisJob(jobId: string): Promise<AnalysisJob> {
  return toJob(await apiFetch<RawAnalysisJob>(`/api/analysis/jobs/${jobId}`));
}

/** Stop a running report. Resolves to the job in its settled state. */
export async function cancelAnalysisJob(jobId: string): Promise<AnalysisJob> {
  return toJob(
    await apiFetch<RawAnalysisJob>(`/api/analysis/jobs/${encodeURIComponent(jobId)}`, {
      method: 'DELETE',
    })
  );
}

/**
 * Report runs still in flight, whoever started them.
 *
 * The page keeps the job id in component state, so navigating away drops it
 * while the run continues. This is how a returning page finds its run again
 * instead of showing the picker as if nothing had been started.
 */
export async function fetchActiveAnalysisJobs(): Promise<AnalysisJob[]> {
  const raw = await apiFetch<RawAnalysisJob[]>('/api/analysis/active-jobs');
  return raw.map(toJob);
}

export async function fetchNotes(): Promise<Note[]> {
  return apiFetch<Note[]>('/api/analysis/notes');
}

export async function createNote(title: string, content: string): Promise<Note[]> {
  return apiFetch<Note[]>('/api/analysis/notes', {
    method: 'POST',
    body: JSON.stringify({ title, content }),
  });
}

export async function deleteNote(id: string): Promise<Note[]> {
  return apiFetch<Note[]>(`/api/analysis/notes/${id}`, { method: 'DELETE' });
}

// ─────────────────────────────────────────────────────────────────────────────
// Profile
//
// These routes are scoped to the authenticated caller server-side — the user id
// comes from the bearer token, which is why no id appears in these paths.
// ─────────────────────────────────────────────────────────────────────────────

export interface Profile {
  id: string;
  email: string;
  full_name?: string;
  avatar_url?: string;
  bio?: string;
  subscription_plan: 'free' | 'pro' | 'whale';
  ai_queries_today: number;
  ai_query_limit: number;
  ai_queries_remaining: number;
  social_links?: SocialLink[];
}

/**
 * One self-declared link on a profile.
 *
 * `url` is null only for Discord, whose usernames are not addressable by URL;
 * the UI copies that one instead of linking it. Nothing about these is
 * verified — do not render a badge against them.
 */
export interface SocialLink {
  platform: string;
  handle: string | null;
  label: string | null;
  url: string | null;
  position: number;
}

export interface SocialLinkInput {
  platform: string;
  handle?: string;
  label?: string;
  url?: string;
}

export interface UserKarma {
  post_karma: number;
  comment_karma: number;
  total_karma: number;
}

/**
 * Another user's profile, as a signed-in caller may see it.
 *
 * There is no `email` here and there must never be one: this object is handed
 * to anyone with an account.
 */
export interface PublicProfile {
  id: string;
  full_name: string | null;
  avatar_url: string | null;
  bio: string | null;
  subscription_plan: string | null;
  created_at: string | null;
  karma: UserKarma;
  social_links: SocialLink[];
}

export async function fetchProfile(): Promise<Profile> {
  return apiFetch<Profile>('/api/profile');
}

export async function updateProfile(update: {
  full_name?: string;
  avatar_url?: string;
  bio?: string;
}): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>('/api/profile', {
    method: 'PUT',
    body: JSON.stringify(update),
  });
}

export async function fetchPublicProfile(userId: string): Promise<PublicProfile> {
  return apiFetch<PublicProfile>(`/api/profile/public/${encodeURIComponent(userId)}`);
}

/** Replaces the caller's whole link set; there is no per-link endpoint. */
export async function updateSocialLinks(
  links: SocialLinkInput[]
): Promise<{ links: SocialLink[] }> {
  return apiFetch<{ links: SocialLink[] }>('/api/profile/social-links', {
    method: 'PUT',
    body: JSON.stringify({ links }),
  });
}

// ==========================================
// SOCIAL — direct messages, blocks, activity
// ==========================================

export interface DmPeer {
  id: string;
  full_name: string | null;
  avatar_url: string | null;
  subscription_plan: string | null;
}

export interface DmPreview {
  body: string;
  sender_id: string | null;
  created_at: string | null;
}

export interface DmConversation {
  id: string;
  peer: DmPeer;
  last_message: DmPreview | null;
  last_message_at: string | null;
  unread_count: number;
}

export interface DmMessage {
  id: string;
  conversation_id: string;
  sender_id: string;
  body: string;
  created_at: string;
}

/**
 * The send gate.
 *
 * `requirements` is what the server currently demands and `status` is what this
 * account actually has, so the UI can show the full checklist — including the
 * rules already satisfied — rather than only what is missing.
 */
export interface DmEligibility {
  can_send: boolean;
  reasons: string[];
  requirements: {
    email_verified: boolean;
    phone_verified: boolean;
    min_account_age_days: number;
  };
  status: {
    email_verified: boolean;
    phone_verified: boolean;
    created_at: string | null;
  };
}

export interface BlockedMember {
  user_id: string;
  full_name: string | null;
  avatar_url: string | null;
  created_at: string | null;
}

export interface CommunityActivity {
  post_count: number;
  comment_count: number;
  post_karma: number;
  comment_karma: number;
  total_karma: number;
  best_post: { id: string; title: string | null; score: number } | null;
}

export async function fetchDmEligibility(): Promise<DmEligibility> {
  return apiFetch<DmEligibility>('/api/social/eligibility');
}

export async function fetchConversations(): Promise<DmConversation[]> {
  const data = await apiFetch<{ conversations: DmConversation[] }>('/api/social/conversations');
  return data.conversations;
}

/** Opens the thread with `userId`, or returns the existing one. */
export async function startConversation(userId: string): Promise<{ id: string; peer_id: string }> {
  return apiFetch<{ id: string; peer_id: string }>('/api/social/conversations', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function fetchMessages(conversationId: string, before?: string): Promise<DmMessage[]> {
  const data = await apiFetch<{ messages: DmMessage[] }>(
    `/api/social/conversations/${encodeURIComponent(conversationId)}/messages`,
    { params: { before } }
  );
  return data.messages;
}

export async function sendMessage(conversationId: string, body: string): Promise<DmMessage> {
  return apiFetch<DmMessage>(
    `/api/social/conversations/${encodeURIComponent(conversationId)}/messages`,
    { method: 'POST', body: JSON.stringify({ body }) }
  );
}

export async function markConversationRead(conversationId: string): Promise<void> {
  await apiFetch<void>(`/api/social/conversations/${encodeURIComponent(conversationId)}/read`, {
    method: 'POST',
  });
}

export async function fetchUnreadCount(): Promise<number> {
  const data = await apiFetch<{ unread: number }>('/api/social/unread-count');
  return data.unread;
}

export async function fetchBlockedMembers(): Promise<BlockedMember[]> {
  const data = await apiFetch<{ blocked: BlockedMember[] }>('/api/social/blocks');
  return data.blocked;
}

export async function blockMember(userId: string): Promise<void> {
  await apiFetch<void>(`/api/social/blocks/${encodeURIComponent(userId)}`, { method: 'POST' });
}

export async function unblockMember(userId: string): Promise<void> {
  await apiFetch<void>(`/api/social/blocks/${encodeURIComponent(userId)}`, { method: 'DELETE' });
}

export async function fetchCommunityActivity(): Promise<CommunityActivity> {
  return apiFetch<CommunityActivity>('/api/social/activity');
}

/**
 * The `user_settings` row.
 *
 * Only `dm_enabled` has a control today — the rest are read here because the
 * endpoint returns the whole row and a partial type would make a later toggle
 * look like a new field rather than an existing one.
 */
export interface UserSettings {
  theme?: string;
  notifications_enabled?: boolean;
  email_alerts?: boolean;
  telegram_alerts?: boolean;
  default_market?: string;
  dm_enabled?: boolean;
}

export async function fetchUserSettings(): Promise<UserSettings> {
  return apiFetch<UserSettings>('/api/profile/settings');
}

export async function updateUserSettings(
  update: Partial<UserSettings>
): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>('/api/profile/settings', {
    method: 'PUT',
    body: JSON.stringify(update),
  });
}

export interface UploadedAvatar {
  url: string;
  path: string;
}

/**
 * Replace the signed-in user's profile photo.
 *
 * `apiFetch` leaves `Content-Type` unset for FormData so the browser can attach
 * the multipart boundary itself — see the note in the function.
 */
export async function uploadAvatar(file: File): Promise<UploadedAvatar> {
  const body = new FormData();
  body.append('file', file);
  return apiFetch<UploadedAvatar>('/api/profile/avatar', { method: 'POST', body });
}

export async function deleteAvatar(): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>('/api/profile/avatar', { method: 'DELETE' });
}

/** Irreversible. `confirmEmail` must be the caller's own address. */
export async function deleteAccount(confirmEmail: string): Promise<void> {
  await apiFetch<void>('/api/profile/account', {
    method: 'DELETE',
    body: JSON.stringify({ confirm_email: confirmEmail }),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Sign-up checks
//
// Anonymous by design: the caller has no session yet. See routers/auth.py for
// why this endpoint is willing to say an address is taken, and what limits it.
// ─────────────────────────────────────────────────────────────────────────────

export interface EmailPrecheck {
  /** False when the address is malformed, disposable, or has no mail server. */
  deliverable: boolean;
  registered: boolean;
  reason: string;
  /** Display-ready. Empty when there is nothing to say. */
  message: string;
}

export async function precheckEmail(email: string): Promise<EmailPrecheck> {
  return apiFetch<EmailPrecheck>('/api/auth/email/precheck', {
    method: 'POST',
    body: JSON.stringify({ email }),
    anonymous: true,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat sessions & history (all scoped to the authenticated caller)
// ─────────────────────────────────────────────────────────────────────────────

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatHistoryMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  session_id?: string;
  thinking_time?: number;
  /** The tool timeline behind an assistant message; null before migration 009. */
  steps?: StoredChatStep[] | null;
  created_at: string;
}

/** One turn's worth of transcript sent back to the backend for context. */
export interface ChatTurnMessage {
  role: 'user' | 'assistant';
  content: string;
}

/** Mirrors `ChatResponse` in backend/routers/chat.py. */
export interface ChatTurnResponse {
  response: string;
  thinking_time: number;
  sources: string[];
  detected_symbol: string | null;
  session_title: string | null;
}

/**
 * Ask Oracle one question.
 *
 * Goes through {@link apiFetch} rather than a bare fetch so a non-2xx reply
 * raises instead of being parsed: the previous bare-fetch call read `response`
 * off a 500's error body, which is `undefined`, and rendered that as the
 * answer. The bearer token matters too — the backend accepts anonymous callers
 * but needs the token to attribute the turn to a session the user owns.
 */
export async function sendChatMessage(request: {
  message: string;
  history?: ChatTurnMessage[];
  session_id?: string;
  style?: 'concise' | 'detailed';
}): Promise<ChatTurnResponse> {
  return apiFetch<ChatTurnResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

/** Whether the chat backend has a reachable LLM provider. Public endpoint. */
export async function fetchChatStatus(): Promise<{ available: boolean }> {
  return apiFetch<{ available: boolean }>('/api/chat/status', { anonymous: true });
}

/**
 * Start a turn as a job and poll it, instead of holding a connection open.
 *
 * The same trade the analysis panel already made: progress is reportable, the
 * run survives a page that navigates away, and a proxy timeout stops being able
 * to kill an answer that was nearly finished.
 */
export async function startChatJob(request: {
  message: string;
  history?: ChatTurnMessage[];
  session_id?: string;
  style?: 'concise' | 'detailed';
}): Promise<ChatJob> {
  const raw = await apiFetch<Record<string, unknown>>('/api/chat/jobs', {
    method: 'POST',
    body: JSON.stringify(request),
  });
  return toChatJob(raw);
}

export async function fetchChatJob(jobId: string): Promise<ChatJob> {
  const raw = await apiFetch<Record<string, unknown>>(`/api/chat/jobs/${jobId}`);
  return toChatJob(raw);
}

/**
 * Stop a turn that is still running.
 *
 * A turn can spend minutes gathering evidence, so a question asked by mistake
 * needs a way out that is not waiting for it to finish. Returns the settled
 * job; the caller decides whether to say anything about it.
 */
export async function cancelChatJob(jobId: string): Promise<ChatJob> {
  const raw = await apiFetch<Record<string, unknown>>(`/api/chat/jobs/${jobId}`, {
    method: 'DELETE',
  });
  return toChatJob(raw);
}

export async function fetchChatSessions(): Promise<ChatSession[]> {
  const data = await apiFetch<{ sessions: ChatSession[] }>('/api/chat/sessions');
  return data.sessions ?? [];
}

export async function createChatSession(title: string): Promise<ChatSession> {
  return apiFetch<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
}

export async function deleteChatSession(sessionId: string): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>(`/api/chat/sessions/${sessionId}`, {
    method: 'DELETE',
  });
}

export async function fetchSessionMessages(sessionId: string): Promise<ChatHistoryMessage[]> {
  const data = await apiFetch<{ messages: ChatHistoryMessage[] }>(
    `/api/chat/sessions/${sessionId}/messages`
  );
  return data.messages ?? [];
}

export async function saveChatMessage(message: {
  role: 'user' | 'assistant';
  content: string;
  session_id?: string;
  thinking_time?: number;
  steps?: StoredChatStep[];
}): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>('/api/chat/history', {
    method: 'POST',
    body: JSON.stringify(message),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Community
// ─────────────────────────────────────────────────────────────────────────────
// Nullable fields are typed `| null` rather than optional: the backend is
// Pydantic, so every key is present on the wire and absent values arrive as
// `null`. Typing them as optional would make `'title' in post` lie.

/** The topical flair. Orthogonal to how the post renders. */
export type CommunityPostType = 'question' | 'thought' | 'analysis';

/** How the post renders. */
export type CommunityPostKind = 'text' | 'image' | 'link';

export type CommunityFeedSort = 'hot' | 'new' | 'top';

export interface CommunityAuthor {
  id: string | null;
  full_name: string | null;
  avatar_url: string | null;
  subscription_plan: string | null;
}

export interface CommunityLinkPreview {
  url: string;
  title: string | null;
  description: string | null;
  image_url: string | null;
  site_name: string | null;
}

export interface CommunityPost {
  id: string;
  type: CommunityPostType;
  post_kind: CommunityPostKind;
  title: string | null;
  content: string;
  asset_symbol: string | null;
  image_url: string | null;
  link: CommunityLinkPreview | null;
  score: number;
  comments_count: number;
  is_edited: boolean;
  created_at: string;
  updated_at: string | null;
  author: CommunityAuthor;
  /** 1, -1, or 0 when the viewer has not voted or is signed out. */
  my_vote: number;
}

export interface CommunityComment {
  id: string;
  post_id: string;
  parent_id: string | null;
  /** Null for a tombstoned comment — the row survives to hold its replies. */
  content: string | null;
  score: number;
  depth: number;
  is_edited: boolean;
  is_deleted: boolean;
  created_at: string;
  updated_at: string | null;
  author: CommunityAuthor;
  my_vote: number;
  replies: CommunityComment[];
}

export interface CommunityFeedPage {
  posts: CommunityPost[];
  has_more: boolean;
}

export interface CommunityCommentThread {
  comments: CommunityComment[];
  total: number;
}

export interface CommunityVoteResult {
  score: number;
  my_vote: number;
}

export interface CommunityTrendingAsset {
  asset_symbol: string;
  post_count: number;
  total_score: number;
}

export interface CommunityBoardStats {
  total_posts: number;
  posts_today: number;
  contributors: number;
}

export interface CommunitySidebarData {
  trending: CommunityTrendingAsset[];
  stats: CommunityBoardStats;
}

export interface CommunityUploadedMedia {
  url: string;
  path: string;
}

export interface CommunityFeedParams {
  sort?: CommunityFeedSort;
  type?: CommunityPostType | 'all';
  symbol?: string;
  limit?: number;
  offset?: number;
}

export interface CreateCommunityPostInput {
  type: CommunityPostType;
  post_kind: CommunityPostKind;
  content: string;
  title?: string;
  asset_symbol?: string;
  image_url?: string;
  link_url?: string;
}

export interface UpdateCommunityPostInput {
  title?: string;
  content?: string;
  asset_symbol?: string;
}

// ── Reads ────────────────────────────────────────────────────────────────────
// These stay authenticated when a session exists: the token is what lets the
// backend fill in `my_vote`, which is why the old like button reset on reload.

export async function fetchCommunityFeed(
  params: CommunityFeedParams = {}
): Promise<CommunityFeedPage> {
  return apiFetch<CommunityFeedPage>('/api/community/posts', {
    params: {
      sort: params.sort ?? 'hot',
      type: params.type === 'all' ? undefined : params.type,
      symbol: params.symbol,
      limit: params.limit ?? 20,
      offset: params.offset ?? 0,
    },
  });
}

export async function fetchUserCommunityPosts(
  userId: string,
  params: { limit?: number; offset?: number } = {}
): Promise<CommunityFeedPage> {
  return apiFetch<CommunityFeedPage>(`/api/community/posts/user/${userId}`, {
    params: { limit: params.limit ?? 20, offset: params.offset ?? 0 },
  });
}

export async function fetchCommunityPost(postId: string): Promise<CommunityPost> {
  return apiFetch<CommunityPost>(`/api/community/posts/${postId}`);
}

export async function fetchCommunityComments(postId: string): Promise<CommunityCommentThread> {
  return apiFetch<CommunityCommentThread>(`/api/community/posts/${postId}/comments`);
}

export async function fetchCommunitySidebar(): Promise<CommunitySidebarData> {
  return apiFetch<CommunitySidebarData>('/api/community/sidebar');
}

// ── Writes ───────────────────────────────────────────────────────────────────

export async function createCommunityPost(post: CreateCommunityPostInput): Promise<CommunityPost> {
  return apiFetch<CommunityPost>('/api/community/posts', {
    method: 'POST',
    body: JSON.stringify(post),
  });
}

export async function updateCommunityPost(
  postId: string,
  patch: UpdateCommunityPostInput
): Promise<CommunityPost> {
  return apiFetch<CommunityPost>(`/api/community/posts/${postId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}

export async function deleteCommunityPost(postId: string): Promise<void> {
  await apiFetch<void>(`/api/community/posts/${postId}`, { method: 'DELETE' });
}

export async function createCommunityComment(
  postId: string,
  input: { content: string; parent_id?: string }
): Promise<CommunityComment> {
  return apiFetch<CommunityComment>(`/api/community/posts/${postId}/comments`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function updateCommunityComment(
  commentId: string,
  content: string
): Promise<CommunityComment> {
  return apiFetch<CommunityComment>(`/api/community/comments/${commentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ content }),
  });
}

export async function deleteCommunityComment(commentId: string): Promise<void> {
  await apiFetch<void>(`/api/community/comments/${commentId}`, { method: 'DELETE' });
}

/** `value` is 1, -1, or 0 to clear an existing vote. */
export async function voteOnCommunityPost(
  postId: string,
  value: number
): Promise<CommunityVoteResult> {
  return apiFetch<CommunityVoteResult>(`/api/community/posts/${postId}/vote`, {
    method: 'POST',
    body: JSON.stringify({ value }),
  });
}

export async function voteOnCommunityComment(
  commentId: string,
  value: number
): Promise<CommunityVoteResult> {
  return apiFetch<CommunityVoteResult>(`/api/community/comments/${commentId}/vote`, {
    method: 'POST',
    body: JSON.stringify({ value }),
  });
}

export async function uploadCommunityMedia(file: File): Promise<CommunityUploadedMedia> {
  const body = new FormData();
  body.append('file', file);
  return apiFetch<CommunityUploadedMedia>('/api/community/media', { method: 'POST', body });
}

export async function fetchCommunityLinkPreview(url: string): Promise<CommunityLinkPreview> {
  return apiFetch<CommunityLinkPreview>('/api/community/link-preview', {
    method: 'POST',
    body: JSON.stringify({ url }),
  });
}

// ── Per-user AI provider ─────────────────────────────────────────────────────
// The API key is write-only: it is sent on save but never returned. `key_hint`
// is the last four characters, for display only.

export interface LLMSettings {
  provider: string;
  model: string;
  key_hint: string;
  configured: boolean;
  use_for_chat: boolean;
  use_for_news: boolean;
  use_for_reports: boolean;
  encryption_available: boolean;
  supported_providers: string[];
}

export interface LLMSettingsUpdate {
  provider: string;
  model?: string;
  api_key?: string;
  use_for_chat?: boolean;
  use_for_news?: boolean;
  use_for_reports?: boolean;
}

export interface LLMTestResult {
  ok: boolean;
  provider?: string;
  models?: string[];
  error?: string;
}

export async function getLLMSettings(): Promise<LLMSettings> {
  return apiFetch<LLMSettings>('/api/profile/llm');
}

export async function updateLLMSettings(data: LLMSettingsUpdate): Promise<LLMSettings> {
  return apiFetch<LLMSettings>('/api/profile/llm', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteLLMSettings(): Promise<{ success: boolean }> {
  return apiFetch<{ success: boolean }>('/api/profile/llm', { method: 'DELETE' });
}

export async function testLLMSettings(
  provider: string,
  model: string,
  apiKey: string
): Promise<LLMTestResult> {
  return apiFetch<LLMTestResult>('/api/profile/llm/test', {
    method: 'POST',
    body: JSON.stringify({ provider, model, api_key: apiKey }),
  });
}

// ==========================================
// ADMIN
//
// Every route below 403s for a non-admin. The panel asks `fetchAdminSession`
// first and hides itself on `is_admin: false`; that is presentation only, the
// server is the boundary. Nullable fields are `| null` rather than optional,
// matching the community section — the wire is Pydantic.
// ==========================================

export interface AdminSessionInfo {
  is_admin: boolean;
  email: string | null;
}

export interface AdminUser {
  id: string;
  email: string | null;
  full_name: string | null;
  avatar_url: string | null;
  subscription_plan: string;
  subscription_expires_at: string | null;
  created_at: string | null;
  banned_until: string | null;
  ban_reason: string | null;
  is_banned: boolean;
  is_admin: boolean;
  posts_count: number;
  comments_count: number;
}

export interface AdminUserPage {
  users: AdminUser[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserListParams {
  search?: string;
  plan?: string;
  status?: 'all' | 'active' | 'banned';
  sort?: 'created_at' | 'email' | 'subscription_plan';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}

export interface AdminPostSummary {
  id: string;
  title: string | null;
  content_preview: string;
  type: string;
  post_kind: string;
  score: number;
  comments_count: number;
  created_at: string | null;
  author_id: string | null;
  author_name: string | null;
  author_email: string | null;
}

export interface AdminPostPage {
  posts: AdminPostSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminOverview {
  total_users: number;
  banned_users: number;
  new_users_7d: number;
  plan_counts: Record<string, number>;
  total_posts: number;
  posts_today: number;
  total_comments: number;
}

export interface AdminAuditEntry {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface AdminAuditPage {
  entries: AdminAuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export async function fetchAdminSession(): Promise<AdminSessionInfo> {
  return apiFetch<AdminSessionInfo>('/api/admin/me');
}

export async function fetchAdminOverview(): Promise<AdminOverview> {
  return apiFetch<AdminOverview>('/api/admin/overview');
}

export async function fetchAdminUsers(params: AdminUserListParams = {}): Promise<AdminUserPage> {
  return apiFetch<AdminUserPage>('/api/admin/users', {
    params: {
      search: params.search || undefined,
      plan: params.plan === 'all' ? undefined : params.plan,
      status: params.status ?? 'all',
      sort: params.sort ?? 'created_at',
      order: params.order ?? 'desc',
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  });
}

export async function setAdminUserPlan(
  userId: string,
  plan: string,
  durationDays?: number
): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/api/admin/users/${userId}/plan`, {
    method: 'POST',
    body: JSON.stringify({ plan, duration_days: durationDays ?? null }),
  });
}

export async function banAdminUser(
  userId: string,
  input: { days?: number; reason?: string } = {}
): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/api/admin/users/${userId}/ban`, {
    method: 'POST',
    body: JSON.stringify({ days: input.days ?? null, reason: input.reason || null }),
  });
}

export async function unbanAdminUser(userId: string): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/api/admin/users/${userId}/unban`, { method: 'POST' });
}

export async function fetchAdminPosts(
  params: { search?: string; limit?: number; offset?: number } = {}
): Promise<AdminPostPage> {
  return apiFetch<AdminPostPage>('/api/admin/content/posts', {
    params: {
      search: params.search || undefined,
      limit: params.limit ?? 25,
      offset: params.offset ?? 0,
    },
  });
}

export async function adminDeletePost(postId: string, reason?: string): Promise<void> {
  await apiFetch<void>(`/api/admin/posts/${postId}`, {
    method: 'DELETE',
    params: { reason: reason || undefined },
  });
}

export async function adminDeleteComment(commentId: string, reason?: string): Promise<void> {
  await apiFetch<void>(`/api/admin/comments/${commentId}`, {
    method: 'DELETE',
    params: { reason: reason || undefined },
  });
}

export async function fetchAdminAudit(
  params: { limit?: number; offset?: number; targetType?: string } = {}
): Promise<AdminAuditPage> {
  return apiFetch<AdminAuditPage>('/api/admin/audit', {
    params: {
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
      target_type: params.targetType || undefined,
    },
  });
}

// ==========================================
// OWNERSHIP — who holds what
// ==========================================

export type OwnershipCategory =
  | 'institution'
  | 'treasury'
  | 'politician'
  | 'onchain'
  | 'central_bank';

export type OwnershipAssetClass =
  | 'equity'
  | 'crypto'
  | 'cash'
  | 'gold'
  | 'fx_reserve'
  | 'bond'
  | 'fund'
  | 'other';

export type OwnershipSourceKind =
  | 'sec_13f'
  | 'sec_form4'
  | 'coingecko_treasury'
  | 'onchain'
  | 'central_bank'
  | 'manual';

/** Whether a USD figure was published as-is, or derived by pricing a quantity. */
export type OwnershipValueBasis = 'reported' | 'marked' | 'unknown';

export type OwnershipMoveKind =
  | 'new'
  | 'add'
  | 'trim'
  | 'exit'
  | 'buy'
  | 'sell'
  | 'transfer_in'
  | 'transfer_out'
  | 'increase'
  | 'decrease';

export interface OwnershipSourceRef {
  kind: OwnershipSourceKind;
  /** Rendered verbatim on the badge — never composed client-side. */
  label: string;
  url: string | null;
  /** The date the figure describes. Null when the source publishes none. */
  as_of: string | null;
  /** When we fetched it — deliberately separate from `as_of`. */
  retrieved_at: string | null;
  manual: boolean;
}

export interface OwnershipPosition {
  key: string;
  label: string;
  symbol: string | null;
  asset_class: OwnershipAssetClass;
  quantity: number | null;
  quantity_unit: string | null;
  value_usd: number | null;
  value_basis: OwnershipValueBasis;
  price_usd: number | null;
  priced_at: string | null;
  weight_pct: number | null;
  /** Null means "no baseline yet", which is not the same as "unchanged". */
  delta_quantity: number | null;
  delta_value_usd: number | null;
  delta_pct: number | null;
  source: OwnershipSourceRef;
  note: string | null;
}

export interface OwnershipAllocationSlice {
  /** Position key, or `__other__` for the pooled tail. Empty on older boards. */
  key: string;
  /** The holding's name. Empty on older boards — fall back to the class label. */
  label: string;
  symbol: string | null;
  asset_class: OwnershipAssetClass;
  value_usd: number;
  pct: number;
}

export interface OwnershipMove {
  id: string;
  entity_id: string;
  entity_name: string;
  category: OwnershipCategory;
  kind: OwnershipMoveKind;
  asset_label: string;
  asset_symbol: string | null;
  asset_class: OwnershipAssetClass;
  quantity_delta: number | null;
  value_usd_delta: number | null;
  pct_delta: number | null;
  occurred_at: string;
  reported_at: string | null;
  headline: string;
  source: OwnershipSourceRef;
}

export interface OwnershipSourceHealth {
  kind: OwnershipSourceKind;
  ok: boolean;
  entities_covered: number;
  as_of: string | null;
  message: string | null;
}

export interface OwnershipEntity {
  id: string;
  name: string;
  subtitle: string | null;
  category: OwnershipCategory;
  country: string | null;
  /** The holder's own mark. Null for anyone no logo identifies. */
  logo_url: string | null;
  total_value_usd: number | null;
  positions_count: number;
  allocation: OwnershipAllocationSlice[];
  /** The largest few holdings — enough for a card, not the full list. */
  top_positions: OwnershipPosition[];
  source_label: string | null;
  last_move: OwnershipMove | null;
  as_of: string | null;
  stale: boolean;
  issues: string[];
  has_data: boolean;
  coverage_note: string | null;
}

export interface OwnershipEntityDetail {
  entity: OwnershipEntity;
  positions: OwnershipPosition[];
  moves: OwnershipMove[];
  sources: OwnershipSourceRef[];
  moves_baseline: boolean;
}

export interface OwnershipBoard {
  entities: OwnershipEntity[];
  latest_moves: OwnershipMove[];
  category_counts: Record<string, number>;
  sources: OwnershipSourceHealth[];
  as_of: string;
  last_refresh_at: string | null;
  next_refresh_at: string | null;
  stale: boolean;
}

export async function fetchOwnershipBoard(): Promise<OwnershipBoard> {
  return apiFetch<OwnershipBoard>('/api/ownership/board', { anonymous: true });
}

export async function fetchOwnershipEntity(entityId: string): Promise<OwnershipEntityDetail> {
  return apiFetch<OwnershipEntityDetail>(
    `/api/ownership/entities/${encodeURIComponent(entityId)}`,
    { anonymous: true }
  );
}

/** One row of a cross-holder ranking. */
export interface OwnershipConsensusRow {
  symbol: string | null;
  label: string;
  asset_class: OwnershipAssetClass;
  holder_count: number;
  total_value_usd: number;
  /** Names for held rankings, ids for traded ones — both render as names. */
  holder_names?: string[];
  holders?: string[];
  /** True when some holders report no USD value, so the total is partial. */
  value_is_partial?: boolean;
}

export interface OwnershipConsensus {
  most_held: OwnershipConsensusRow[];
  most_bought: OwnershipConsensusRow[];
  most_sold: OwnershipConsensusRow[];
  entity_count: number;
}

export interface OwnershipAssetOwner {
  entity_id: string;
  entity_name: string;
  label: string;
  symbol: string | null;
  quantity: number | null;
  quantity_unit: string | null;
  value_usd: number | null;
  weight_pct: number | null;
  delta_pct: number | null;
  source: OwnershipSourceRef;
}

export async function fetchOwnershipConsensus(): Promise<OwnershipConsensus> {
  return apiFetch<OwnershipConsensus>('/api/ownership/consensus', { anonymous: true });
}

export async function fetchAssetOwners(
  symbol: string
): Promise<{ symbol: string; owners: OwnershipAssetOwner[] }> {
  return apiFetch<{ symbol: string; owners: OwnershipAssetOwner[] }>(
    `/api/ownership/assets/${encodeURIComponent(symbol)}`,
    { anonymous: true }
  );
}

export async function fetchWatchlistOverlap(): Promise<{ overlap: OwnershipConsensusRow[] }> {
  return apiFetch<{ overlap: OwnershipConsensusRow[] }>('/api/ownership/watchlist-overlap', {
    anonymous: true,
  });
}

/** Holders on one side of one asset, for the quarter. */
export interface OwnershipFlowSide {
  symbol: string;
  label: string;
  holders: string[];
  holder_count: number;
  total_value_usd: number;
}

/** An asset some holders added and others trimmed in the same quarter. */
export interface OwnershipContested {
  symbol: string;
  buyers: string[];
  sellers: string[];
}

/**
 * Last quarter's 13F activity, aggregated.
 *
 * Every dollar figure is as-filed at the same quarter end, which is the only
 * reason summing them is legitimate here. `value_is_partial` means some moves
 * carried no filed value, so the totals are floors — never present them as
 * totals, and never render a missing figure as zero.
 */
export interface OwnershipFlowFacts {
  quarter: string;
  period: string;
  filed_from: string | null;
  filed_to: string | null;
  tilt: 'net_buying' | 'net_selling' | 'balanced' | 'insufficient';
  gross_bought_usd: number;
  gross_sold_usd: number;
  net_usd: number;
  buy_count: number;
  sell_count: number;
  entities_reporting: number;
  entities_tracked: number;
  unpriced_moves: number;
  value_is_partial: boolean;
  /** Moves from treasury, on-chain and insider sources, deliberately excluded. */
  other_activity_count: number;
  headlines: string[];
  consensus_bought: OwnershipFlowSide[];
  consensus_sold: OwnershipFlowSide[];
  contested: OwnershipContested[];
  /** Holders with a single filing on record, so no change is computable for them. */
  baseline_entities: string[];
}

/** `facts` is null when no board exists or no holder has a comparable quarter. */
export interface OwnershipFlowNote {
  facts: OwnershipFlowFacts | null;
  note: AiNote;
}

export async function fetchOwnershipFlowNote(): Promise<OwnershipFlowNote> {
  return apiFetch<OwnershipFlowNote>('/api/ownership/flow-note', { anonymous: true });
}

// ==========================================
// LIVE TAB
// ==========================================

/** What kind of event this is — the filter strip on the Live tab switches on it. */
export type LiveEventKind = 'central_bank' | 'political' | 'macro_data' | 'corporate';

/** Where an event sits relative to now. Derived server-side on every request. */
export type LiveEventStatus = 'scheduled' | 'live' | 'ended';

export type LiveEventImpact = 'high' | 'medium' | 'low';

export interface LiveEvent {
  id: string;
  source: 'forexfactory' | 'federalreserve' | 'youtube' | 'nasdaq';
  kind: LiveEventKind;
  /** Duration bucket the server placed it in — `data`, `speech`, `presser`, ... */
  shape: string;
  title: string;
  /** Secondary line: the Fed's own description of the entry, when it has one. */
  detail: string | null;
  speaker: string | null;
  country: string | null;
  impact: LiveEventImpact;
  /** ISO-8601, always UTC. Formatted for display in the browser, never on the server. */
  starts_at: string;
  /** `starts_at` plus a per-shape duration; what `status` is derived against. */
  ends_at: string;
  status: LiveEventStatus;
  /** False when the source scheduled a day but no time — such a row never reports live. */
  time_confirmed: boolean;
  forecast: string | null;
  previous: string | null;
  watch_url: string | null;
  embed_url: string | null;
  location: string | null;
}

export interface LiveEventsResponse {
  live: LiveEvent[];
  upcoming: LiveEvent[];
  recent: LiveEvent[];
  as_of: string;
  stale: boolean;
}

export interface LiveStreamChannel {
  key: string;
  name: string;
  channel_id: string;
  /** "market" for a rolling 24/7 news channel; otherwise the event kind it corroborates. */
  implies: string;
  is_live: boolean;
  video_id: string | null;
  title: string | null;
  watch_url: string | null;
  /** Always present: falls back to YouTube's keyless channel-live embed. */
  embed_url: string;
  /** The probe could not reach YouTube — distinct from a channel being offline. */
  probe_failed: boolean;
}

export interface LiveStreamsResponse {
  channels: LiveStreamChannel[];
  as_of: string;
  stale: boolean;
}

export interface LiveTapeItem {
  id: string;
  text: string;
  source: string;
  published_at: string;
  url: string | null;
  symbol: string | null;
  tags: string[];
}

export interface LiveTapeResponse {
  items: LiveTapeItem[];
  as_of: string;
  /** The news cache has not been filled yet — not the same as a quiet tape. */
  warming: boolean;
}

// Unguarded like fetchMacroCalendar: an outage swallowed into empty arrays would
// render as "nothing is happening in the world", which is a claim, not a gap.
export async function fetchLiveEvents(): Promise<LiveEventsResponse> {
  return apiFetch<LiveEventsResponse>('/api/live/events');
}

export async function fetchLiveStreams(): Promise<LiveStreamsResponse> {
  return apiFetch<LiveStreamsResponse>('/api/live/streams');
}

export async function fetchLiveTape(limit = 50): Promise<LiveTapeResponse> {
  return apiFetch<LiveTapeResponse>('/api/live/tape', { params: { limit } });
}

export interface LiveStreamer {
  key: string;
  name: string;
  platform: 'youtube' | 'kick';
  region: 'tr' | 'global' | null;
  focus: 'markets' | 'crypto' | 'broker' | 'research' | null;
  is_live: boolean;
  title: string | null;
  /** Kick reports a concurrent-viewer count; YouTube does not, so this is often null. */
  viewers: number | null;
  url: string | null;
  /** The platform could not be reached — distinct from the streamer being off air. */
  probe_failed: boolean;
}

export interface LiveStreamersResponse {
  streamers: LiveStreamer[];
  live_count: number;
  as_of: string;
  stale: boolean;
}

export async function fetchLiveStreamers(): Promise<LiveStreamersResponse> {
  return apiFetch<LiveStreamersResponse>('/api/live/streamers');
}

// ==========================================
// CHAINS PAGE
// ==========================================

/** Which adapter read the chain. Decides what a row can and cannot report. */
export type ChainFamily = 'evm' | 'bitcoin' | 'solana' | 'tron';

/**
 * What a chain's load reading actually measures.
 *
 * Deliberately not normalised away: the three are not the same quantity, and a
 * single "congestion %" across all of them would be a comparison the data does
 * not support. The UI prints the basis next to the bar.
 */
export type ChainLoadBasis =
  /** gasUsed / gasLimit on the newest block. */
  | 'block_fullness'
  /** Projected blocks whose median fee is still bidding for space. */
  | 'fee_contested_backlog'
  /** Share of Solana's scheduled slots that no leader produced. */
  | 'skipped_slots';

export interface ChainLoad {
  percent: number;
  basis: ChainLoadBasis;
}

export interface ChainBlock {
  height: number;
  /**
   * The block's own hash, in whatever form its chain publishes — hex with an
   * `0x` prefix on the EVM chains, bare hex on Bitcoin and TRON, base58 on
   * Solana. Null when the source omitted it. See `shortenHash`.
   */
  hash?: string | null;
  /** Null when the source published the block without a timestamp. */
  timestamp_ms: number | null;
  tx_count: number | null;
  /** Null where the chain has no meaningful capacity ceiling — see `ChainRow`. */
  fill_percent: number | null;
  gas_used?: number | null;
  gas_limit?: number | null;
  size_bytes?: number | null;
  /**
   * Solana only: this row is a group of scheduled slots, not one block, and
   * these two say how many of them produced a block. Ten individual slots would
   * span four seconds, so the stream groups them to cover a comparable window —
   * and the pair doubles as the row's own capacity reading, which is why the
   * bar can be drawn segment by segment.
   */
  slots_produced?: number;
  slots_scheduled?: number;
}

export interface ChainFee {
  /** Cost of the chain's simplest value transfer, in its own coin. */
  transfer_native: number | null;
  transfer_usd: number | null;
  gas_price_gwei?: number | null;
  base_fee_gwei?: number | null;
  /** OP-stack only: the part of the bill that pays to post data to Ethereum. */
  l1_data_fee_native?: number | null;
  /** Bitcoin quotes per virtual byte, across four urgency tiers. */
  fastest_sat_vb?: number | null;
  half_hour_sat_vb?: number | null;
  hour_sat_vb?: number | null;
  economy_sat_vb?: number | null;
  /** The fee is a protocol constant, not a live quote — Solana and TRON. */
  is_fixed?: boolean;
  /** Why the fee is zero, when it is genuinely zero rather than unmeasured. */
  free_reason?: string;
}

export interface ChainRow {
  key: string;
  name: string;
  /** Ticker fees are paid in. Five of the eight rows settle in ETH. */
  symbol: string;
  family: ChainFamily;
  /** The cadence the protocol aims for, which is what `block_time_seconds` is read against. */
  target_block_seconds: number;
  explorer_block_url: string;
  /**
   * Leading characters of `ChainBlock.hash` that encode the height rather than
   * the digest, and which a short label must skip. Non-zero on TRON only.
   */
  hash_height_prefix_chars?: number;
  height: number | null;
  /** When the newest block landed. Null on Solana, which is not dated per slot. */
  last_block_at: number | null;
  block_time_seconds: number | null;
  /** How long a window the cadence was averaged over. */
  cadence_span_seconds: number | null;
  tx_count: number | null;
  /** Null where the chain publishes no capacity this can be measured against. */
  load: ChainLoad | null;
  fee: ChainFee | null;
  /** Newest first. */
  blocks: ChainBlock[];
  /**
   * Present only when `blocks` rows are groups rather than single blocks, and
   * carrying how many slots each row covers. Solana only.
   */
  stream_bucket_slots?: number;
  /** Native coin burned per day, where the chain burns any. */
  burn_native_per_day?: number | null;
  mempool?: {
    tx_count: number | null;
    vsize: number | null;
    /** Blocks deep in transactions that are actually bidding for space. */
    backlog_blocks: number | null;
    /** Blocks deep counting everything queued, dust included. */
    raw_backlog_blocks: number | null;
    contested_fee_threshold_sat_vb: number | null;
    total_fee_sat: number | null;
  };
  throughput?: {
    tps: number | null;
    /** Excludes consensus voting, which is about half of Solana's headline TPS. */
    non_vote_tps: number | null;
    skipped_slot_percent: number | null;
  };
  economics?: {
    hashrate?: number | null;
    difficulty?: number | null;
    difficulty_change_percent?: number | null;
    difficulty_progress_percent?: number | null;
    difficulty_retarget_at?: number | null;
    difficulty_blocks_remaining?: number | null;
    halving_height?: number | null;
    halving_blocks_remaining?: number | null;
    halving_estimated_at?: number | null;
    epoch?: number | null;
    epoch_progress_percent?: number | null;
    epoch_ends_at?: number | null;
    block_height?: number | null;
  };
  /** Why this chain could not be read. Null on every row that reported. */
  error: string | null;
}

export interface ChainFlowAsset {
  symbol: string;
  /** Positive means more value moved onto exchanges than off them. */
  net_flow_usd: number | null;
  active_addresses: number | null;
  transactions: number | null;
}

export interface ChainsBoardResponse {
  chains: ChainRow[];
  /**
   * Daily exchange flow. Covers BTC and ETH only — the free tier this reads
   * refuses the other assets, so the strip names its own limit rather than
   * showing six chains as zero.
   */
  flows: { assets: ChainFlowAsset[]; as_of: string | null };
  prices: Record<string, number | null>;
  as_of: string;
  stale: boolean;
}

/**
 * The Chains board.
 *
 * Unguarded, like the other board fetchers: a failure has to surface as an
 * error state. Note the endpoint itself rarely fails — it is eight independent
 * providers and reports a dead chain as a row carrying `error`, so the page's
 * usual "something is wrong" path is per row, not per request.
 */
export async function fetchChainsBoard(): Promise<ChainsBoardResponse> {
  return apiFetch<ChainsBoardResponse>('/api/chains/board');
}

/**
 * One detected condition, with a sentence already written for it server-side.
 *
 * `basis` is what the reading was measured against — a count of prior days, an
 * hour band, the current mempool. It is not optional context: "fees are high"
 * and "fees are high for this hour of day" are different claims.
 */
export interface ChainAnomaly {
  chain: string;
  chain_name: string;
  kind: string;
  severity: 'high' | 'notable';
  text: string;
  basis: string;
  window: string | null;
  magnitude: number;
}

/**
 * What on the board is not normal.
 *
 * `anomalies` is computed in Python and is the product; `note` is commentary. An
 * unreachable model costs the sentence and never the detection. An empty
 * `anomalies` means the board is quiet, which is why the strip renders nothing
 * at all rather than an "all normal" banner.
 */
export interface ChainAnomalyReport {
  anomalies: ChainAnomaly[];
  /** Detected but not shown, because only the worst few fit on one line. */
  suppressed: number;
  checked: string[];
  /** Chain key to why it could not be judged. A gap, never a quiet network. */
  not_checkable: Record<string, string>;
  coverage: string;
  as_of: string | null;
  stale: boolean;
  note: AiNote;
}

export async function fetchChainAnomalies(): Promise<ChainAnomalyReport> {
  return apiFetch<ChainAnomalyReport>('/api/chains/anomalies');
}
