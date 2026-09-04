/**
 * Typed access to the Borsa İstanbul surface, `/api/bist/*`.
 *
 * A file of its own rather than more of `lib/api.ts`, which is already 3600
 * lines: BIST is a self-contained realm with its own vocabulary, and keeping it
 * separate means a reader of either surface is not paging past the other. The
 * house rule is kept — every response interface sits directly above the fetcher
 * that returns it, and everything goes through `apiFetch`.
 *
 * Every endpoint here is public, so every call passes `{ anonymous: true }`.
 *
 * Two fields recur across almost every payload and both must reach the screen:
 * `delay_minutes` (Borsa İstanbul data is at least fifteen minutes behind) and
 * `stale` (the board is a replay of the last good fetch because the upstream is
 * currently unreachable).
 */

import type { AiNote } from '@/lib/ai-note';
import { apiFetch } from '@/lib/api';

/**
 * One return, in the three frames a Turkish reader needs it in.
 *
 * `real === null` means the inflation series for that window is unavailable —
 * it does **not** mean inflation was zero. The distinction is the whole reason
 * this realm exists, so it is a nullable field rather than a defaulted number.
 */
export interface FramedReturn {
  nominal: number;
  real: number | null;
  usd: number | null;
}

/** What the real columns on a board were computed against. */
export interface RealReturnMeta {
  inflation_yoy: number | null;
  usdtry: number | null;
  /** Window keys that could actually be deflated, e.g. `["1y"]` with no EVDS key. */
  deflatable_windows: string[];
}

// ── Equities ───────────────────────────────────────────────────────────────

export interface BistStock {
  ticker: string;
  /** Venue-qualified, e.g. `BIST:THYAO`. */
  symbol: string;
  name: string;
  price: number | null;
  change_pct: number | null;
  change_abs: number | null;
  volume: number | null;
  traded_value: number | null;
  market_cap: number | null;
  pe: number | null;
  pb: number | null;
  ev_ebitda: number | null;
  free_float_pct: number | null;
  sector: string;
  /** Bare index codes this stock belongs to, e.g. `["XU100", "XU030"]`. */
  indices: string[];
  perf_ytd: number | null;
  perf_1y: number | null;
  week52_high: number | null;
  week52_low: number | null;
  rsi: number | null;
  relative_volume: number | null;
  beta: number | null;
  returns: Record<string, FramedReturn>;
}

export interface BistStocksResponse {
  as_of: string;
  stale: boolean;
  delay_minutes: number;
  total: number;
  matched: number;
  sectors: string[];
  real_return: RealReturnMeta;
  stocks: BistStock[];
}

export interface BistStocksQuery {
  index?: string;
  sector?: string;
  search?: string;
  sort_by?: string;
  descending?: boolean;
  limit?: number;
}

export async function fetchBistStocks(query: BistStocksQuery = {}): Promise<BistStocksResponse> {
  return apiFetch<BistStocksResponse>('/api/bist/stocks', {
    params: { ...query },
    anonymous: true,
  });
}

// ── Isı haritası ───────────────────────────────────────────────────────────

export interface BistHeatmapTile {
  ticker: string;
  symbol: string;
  name: string;
  sector: string;
  price: number | null;
  /** Daily move as a **fraction** — `0.024` is %2,4. */
  change_pct: number | null;
  /** Turnover in lira, raw. */
  traded_value: number | null;
  volume: number | null;
  /** The tile's area. Null means unknown size, not zero. */
  market_cap: number | null;
  indices: string[];
  /** Whether VİOP lists any contract on this underlying. */
  has_futures: boolean;
  /** How many expiries; zero when there are no futures. */
  contracts: number;
  open_interest: number | null;
  open_interest_change: number | null;
  /** Change against yesterday's position, as a **fraction**. */
  open_interest_change_pct: number | null;
}

export interface BistHeatmapSector {
  sector: string;
  count: number;
  market_cap: number;
  /** Share of the scoped index, as a fraction. */
  weight: number;
  /** Capitalisation-weighted move, as a fraction. */
  change_pct: number | null;
  advancers: number;
  decliners: number;
}

export interface BistHeatmapResponse {
  as_of: string;
  stale: boolean;
  delay_minutes: number;
  index: string;
  available_indices: string[];
  /** Listings in the scoped index, before `limit`. */
  total: number;
  shown: number;
  total_market_cap: number;
  /**
   * False when the futures board could not be read at all.
   *
   * Separate from a tile's `has_futures`: one says the column is missing for
   * everyone, the other says this particular name has no contracts.
   */
  has_futures_data: boolean;
  futures_covered: number;
  viop_as_of: string | null;
  viop_stale: boolean | null;
  sectors: BistHeatmapSector[];
  tiles: BistHeatmapTile[];
}

export interface BistHeatmapQuery {
  index?: string;
  limit?: number;
}

export async function fetchBistHeatmap(query: BistHeatmapQuery = {}): Promise<BistHeatmapResponse> {
  return apiFetch<BistHeatmapResponse>('/api/bist/heatmap', {
    params: { ...query },
    anonymous: true,
  });
}

export interface BistCandle {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number;
  volume: number | null;
}

export interface BistStockDetail extends BistStock {
  delay_minutes: number;
  real_return: RealReturnMeta;
  candles: BistCandle[];
  /** A grounded sentence about the year, in Turkish. Decoration on a complete
   *  payload — `unavailable` whenever the model chain cannot answer. */
  ai_note: AiNote;
}

export async function fetchBistStock(
  ticker: string,
  range: string = '1y'
): Promise<BistStockDetail> {
  return apiFetch<BistStockDetail>(`/api/bist/stocks/${encodeURIComponent(ticker)}`, {
    params: { range },
    anonymous: true,
  });
}

// ── Overview ───────────────────────────────────────────────────────────────

export interface BistIndex {
  code: string;
  name: string;
  value: number | null;
  change_pct: number | null;
  change_abs: number | null;
  perf_ytd: number | null;
  perf_1y: number | null;
}

export interface BistSector {
  sector: string;
  count: number;
  market_cap: number;
  /** Share of total listed capitalisation, as a fraction. */
  weight: number;
  change_pct: number | null;
  advancers: number;
  decliners: number;
}

export interface BistMacro {
  inflation_yoy: number | null;
  ppi_yoy: number | null;
  policy_rate: number | null;
  cpi_index: number | null;
  unemployment: number | null;
  gdp_yoy: number | null;
  usdtry: number | null;
  eurtry: number | null;
  as_of: string;
  stale: boolean;
  /** Fisher, not subtraction — the policy rate net of inflation. */
  real_policy_rate: number | null;
}

/**
 * One input to the fear-and-greed index, already scored and already explained.
 *
 * `reading` is what was measured in the units it was measured in — the bar
 * shows a score and the reading is how a reader checks it.
 */
export type BistSentimentHorizon = 'session' | 'trend' | 'year';

export interface BistSentimentComponent {
  key: string;
  label: string;
  /** 0 = maximum fear, 100 = maximum greed. */
  score: number;
  reading: string;
  /**
   * Which third of the index this competes for. Each horizon carries equal
   * weight, so a single session cannot move the score more than a third.
   */
  horizon: BistSentimentHorizon;
  /** Share of the composite, summing to one across the components. */
  weight: number;
}

export interface BistSentiment {
  score: number;
  /** Turkish band: `Aşırı korku` … `Aşırı açgözlülük`. */
  label: string;
  measured: number;
  components: BistSentimentComponent[];
}

/**
 * What carries the index whether or not the rest of the board agrees.
 *
 * Two readings answering different questions: the largest sector's share of
 * capitalisation is structural, the turnover shares are today's.
 */
export interface BistDominance {
  sector: string | null;
  /** Fraction of total listed capitalisation. */
  sector_weight: number | null;
  /** That sector's own capitalisation-weighted move today, as a fraction. */
  sector_change_pct: number | null;
  top_ticker: string | null;
  top_turnover_share: number | null;
  top5_turnover_share: number | null;
}

export interface BistOverview {
  as_of: string;
  stale: boolean;
  delay_minutes: number;
  indices: BistIndex[];
  breadth: { advancers: number; decliners: number; unchanged: number; total: number };
  sectors: BistSector[];
  gainers: BistStock[];
  losers: BistStock[];
  most_traded: BistStock[];
  macro: BistMacro | null;
  /** Null when the board was too thin to measure — never a placeholder score. */
  sentiment: BistSentiment | null;
  dominance: BistDominance;
}

export async function fetchBistOverview(): Promise<BistOverview> {
  return apiFetch<BistOverview>('/api/bist/overview', { anonymous: true });
}

// ── Funds ──────────────────────────────────────────────────────────────────

/**
 * A fund's portfolio split as the screener carries it: bucket key to weight.
 *
 * Sparse — an absent bucket means the fund does not hold it. Weights are
 * fractions, like `returns`, and are what TEFAS reported rather than a set
 * scaled to sum to one.
 */
export type FundAllocationWeights = Record<string, number>;

export interface FundAllocationBucketMeta {
  key: string;
  label: string;
}

/** The board-wide facts about the column, sent once instead of per fund. */
export interface BistFundsAllocationMeta {
  /** The TEFAS publication date every row on the board was read from. */
  as_of: string;
  /** True when TEFAS could not be reached and this is a replayed snapshot. */
  stale: boolean;
  /** How many funds on the board TEFAS published a split for. */
  reported: number;
  /** Key to label, in bar order. The order is what makes two bars comparable. */
  buckets: FundAllocationBucketMeta[];
}

export interface BistFundAllocationLine {
  /** The raw TEFAS instrument code, e.g. `hs`. */
  code: string;
  label: string;
  weight: number;
}

export interface BistFundAllocationBucket {
  key: string;
  label: string;
  weight: number;
  lines: BistFundAllocationLine[];
}

export interface BistFundAllocation {
  as_of: string;
  /** Everything TEFAS reported, summed. Below 1 leaves the bar's tail bare. */
  total: number;
  buckets: BistFundAllocationBucket[];
}

export interface BistFund {
  code: string;
  title: string;
  /** Şemsiye fon type, e.g. "Hisse Senedi Şemsiye Fonu". */
  umbrella: string;
  tradable: boolean;
  /** TEFAS's own 1–7 grade, not derived from the price series. */
  risk_value: number | null;
  returns: Record<string, number | null>;
  framed_returns: Record<string, FramedReturn>;
  /** Null means TEFAS published no split for this fund — not that it holds nothing. */
  allocation: FundAllocationWeights | null;
}

/**
 * How much of the board gained in lira and lost in purchasing power.
 *
 * Computed server-side across every fund rather than the page requested, so it
 * is a fact about the market rather than about the slice on screen.
 */
export interface RealLossSummary {
  window: string;
  /** Funds that had both a nominal figure and a deflator for the window. */
  measured: number;
  /** Of those, how many were a nominal gain and a real loss. */
  count: number;
  /** The largest nominal gain that still ended negative — the clearest case. */
  example: { code: string; title: string; nominal: number; real: number } | null;
}

export interface BistFundsResponse {
  fund_type: string;
  fund_type_label: string;
  risk_free_rate: number | null;
  /** How the rate was obtained — `"money_market_median"` when derived here. */
  risk_free_source: string | null;
  stale: boolean;
  total: number;
  matched: number;
  umbrellas: string[];
  real_return: RealReturnMeta;
  real_loss: RealLossSummary;
  /** Null means the column could not be built at all, for any fund. */
  allocation: BistFundsAllocationMeta | null;
  funds: BistFund[];
}

export interface BistFundsQuery {
  fund_type?: string;
  umbrella?: string;
  search?: string;
  tradable_only?: boolean;
  max_risk?: number;
  sort_by?: string;
  limit?: number;
}

export async function fetchBistFunds(query: BistFundsQuery = {}): Promise<BistFundsResponse> {
  return apiFetch<BistFundsResponse>('/api/bist/funds', {
    params: { ...query },
    anonymous: true,
  });
}

export interface BistFundMetrics {
  observations: number;
  total_return: number | null;
  annualised_return: number | null;
  volatility: number | null;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown: number | null;
  /** Observations from the trough back to the prior peak. Null = never recovered. */
  recovery_days: number | null;
}

export interface BistFundDetail {
  code: string;
  title: string;
  umbrella: string;
  risk_value: number | null;
  tradable: boolean;
  category_rank: number | null;
  category_size: number | null;
  months: number;
  published_returns: Record<string, number | null>;
  framed_returns: Record<string, FramedReturn>;
  risk_free_rate: number | null;
  allocation: BistFundAllocation | null;
  series: { date: string; price: number }[];
  metrics: BistFundMetrics;
  real_return: RealReturnMeta;
  /** See `BistStockDetail.ai_note`. */
  ai_note: AiNote;
}

export async function fetchBistFund(code: string, months: number = 12): Promise<BistFundDetail> {
  return apiFetch<BistFundDetail>(`/api/bist/funds/${encodeURIComponent(code)}`, {
    params: { months },
    anonymous: true,
  });
}

export interface BistFundHolding {
  /** BIST code, e.g. `THYAO`. The identity — the label is only a fallback. */
  ticker: string;
  /** Issuer name as the filing prints it. Often clipped by the PDF's columns. */
  label: string;
  /** Market value in lira, on the report's date. */
  value: number;
  /** Share of the fund's **equity book**, not of the fund. See `total_value`. */
  weight: number;
}

/**
 * Why a fund has no holdings to show. Four different sentences, because
 * collapsing them would tell a reader the fund owns no stocks — which is only
 * true for one of them.
 */
export type BistFundHoldingsReason =
  | 'no_report'
  | 'no_equity'
  | 'unreadable'
  | 'not_listed'
  | 'unavailable';

export interface BistFundHoldingsResponse {
  code: string;
  reason: BistFundHoldingsReason | null;
  stale: boolean;
  as_of: {
    year: number;
    /** Calendar month the report covers, 1-12. */
    period: number;
    published: string | null;
    /** KAP's own late-filing flag — the usual reason a book is two months old. */
    late: boolean;
  } | null;
  /** The KAP disclosure, so any figure here can be checked against the filing. */
  source_url: string | null;
  /** The equity book in lira: the denominator every `weight` is struck against. */
  total_value: number | null;
  holdings: BistFundHolding[];
}

export async function fetchBistFundHoldings(
  code: string,
  fundType: string = 'YAT'
): Promise<BistFundHoldingsResponse> {
  return apiFetch<BistFundHoldingsResponse>(
    `/api/bist/funds/${encodeURIComponent(code)}/holdings`,
    { params: { fund_type: fundType }, anonymous: true }
  );
}

export interface BistFundComparison {
  months: number;
  requested: string[];
  /** Codes that did not resolve. Named so a missing line is never mistaken for a flat one. */
  unresolved: string[];
  funds: BistFundDetail[];
}

export async function fetchBistFundComparison(
  codes: string[],
  months: number = 12
): Promise<BistFundComparison> {
  return apiFetch<BistFundComparison>('/api/bist/funds/compare', {
    params: { codes: codes.join(','), months },
    anonymous: true,
  });
}

// ── Market-wide notes ──────────────────────────────────────────────────────

/**
 * A sector's contribution to the day, as the market note reports it.
 *
 * Percentages here are already **points**, not fractions. The backend quantizes
 * each reading to a bucket before it fingerprints the note, and handing the
 * frontend the fraction back would invite a second rounding that disagreed with
 * the sentence beside it. So these render with `formatNumber`, never
 * `formatPercent` — which is the opposite of every other type in this file.
 */
export interface BistMarketSector {
  sector: string;
  count: number;
  change_pct: number | null;
  weight_pct: number | null;
  advancers: number;
  decliners: number;
}

/**
 * Whether the index and the breadth agreed, and which way.
 *
 * Computed on the server before the model saw it. The panel prints the label and
 * the model explains it — the same split every AI surface here uses.
 */
export type BistMarketStance =
  | 'narrow_rally'
  | 'broad_rally'
  | 'narrow_selloff'
  | 'broad_selloff'
  | 'mixed';

export interface BistMarketFacts {
  stance: BistMarketStance;
  as_of: string | null;
  stale: boolean;
  index: {
    code: string;
    name: string | null;
    value: number | null;
    change_pct: number | null;
    ytd_pct: number | null;
    year_nominal_pct: number | null;
    year_real_pct: number | null;
  };
  breadth: {
    advancers: number;
    decliners: number;
    unchanged: number;
    total: number;
    advancer_pct: number | null;
  };
  /** Null when the board was too thin to measure — never a placeholder score. */
  sentiment: {
    score: number | null;
    label: string;
    measured: number;
    components: { key: string; label: string; score: number | null; reading: string }[];
  } | null;
  leaders: BistMarketSector[];
  laggards: BistMarketSector[];
  concentration: {
    sector: string | null;
    sector_weight_pct: number | null;
    sector_change_pct: number | null;
    top_ticker: string | null;
    top_turnover_pct: number | null;
    top5_turnover_pct: number | null;
    concentrated: boolean;
  };
  valuation: { median_pe: number | null; median_pb: number | null; measured: number };
  macro: {
    inflation_pct: number | null;
    ppi_pct: number | null;
    policy_rate_pct: number | null;
    real_policy_rate_pct: number | null;
    unemployment_pct: number | null;
    gdp_pct: number | null;
    usdtry: number | null;
    as_of: string;
  } | null;
  viop: { total: number | null; stale: boolean } | null;
  /** Readings this call deliberately does not carry, named rather than implied. */
  not_measured: string[];
}

/**
 * `facts` is null when the board could not be read at all.
 *
 * Not the same as a quiet market, and the panel must not render it as one — it
 * draws nothing instead.
 */
export interface BistMarketNoteResponse {
  facts: BistMarketFacts | null;
  note: AiNote;
}

export async function fetchBistMarketNote(): Promise<BistMarketNoteResponse> {
  return apiFetch<BistMarketNoteResponse>('/api/bist/market-note', { anonymous: true });
}

export type BistFundsMarketStance = 'beating_inflation' | 'losing_to_inflation' | 'split';

export interface BistUmbrellaStat {
  umbrella: string;
  count: number;
  median_nominal_pct: number | null;
  median_real_pct: number | null;
}

export interface BistFundsMarketFacts {
  stance: BistFundsMarketStance;
  fund_type: string;
  fund_type_label: string;
  stale: boolean;
  total: number;
  tradable: number;
  measured: number;
  median_nominal_pct: number | null;
  median_real_pct: number | null;
  /** How far apart the board's funds ended — what a sorted table cannot show. */
  spread: {
    p10_real_pct: number | null;
    p90_real_pct: number | null;
    width_pct: number | null;
    measured: number;
  };
  inflation: {
    beat_count: number;
    measured: number;
    beat_pct: number | null;
    inflation_pct: number | null;
    nominal_gain_real_loss: number;
    nominal_gain_real_loss_measured: number;
    example: { code: string; nominal_pct: number | null; real_pct: number | null } | null;
  };
  risk_free: { rate_pct: number | null; source: string | null; beat_count: number | null };
  leaders: BistUmbrellaStat[];
  laggards: BistUmbrellaStat[];
  risk_cohorts: {
    key: string;
    label: string;
    count: number;
    median_nominal_pct: number | null;
    median_real_pct: number | null;
  }[];
  deflatable_windows: string[];
}

export interface BistFundsMarketNoteResponse {
  facts: BistFundsMarketFacts | null;
  note: AiNote;
}

export async function fetchBistFundsMarketNote(
  fundType: string
): Promise<BistFundsMarketNoteResponse> {
  return apiFetch<BistFundsMarketNoteResponse>('/api/bist/funds/market-note', {
    params: { fund_type: fundType },
    anonymous: true,
  });
}

// ── Macro ──────────────────────────────────────────────────────────────────

export interface BistMacroResponse extends BistMacro {
  cpi_series: { month: string; index: number }[];
  /** `"evds"` when the series is present; null when no key is configured. */
  cpi_source: string | null;
  usdtry_series: { date: string; rate: number }[];
  deflators: Record<string, number | null>;
}

export async function fetchBistMacro(fxRange: string = '5y'): Promise<BistMacroResponse> {
  return apiFetch<BistMacroResponse>('/api/bist/macro', {
    params: { fx_range: fxRange },
    anonymous: true,
  });
}

export type BistMacroStance = 'real_positive' | 'real_near_zero' | 'real_negative';

/**
 * Every figure here is already in **percentage points**, bucketed server-side,
 * so these go through `formatPoints` and never `formatPercent` — see the header
 * of `lib/bist-market-note.ts`. The lira levels are plain rates.
 */
export interface BistMacroFacts {
  stance: BistMacroStance;
  as_of: string | null;
  stale: boolean;
  rates: {
    policy_pct: number | null;
    inflation_pct: number | null;
    ppi_pct: number | null;
    /** Fisher, not subtraction — the one figure a reader works out wrong in their head. */
    real_policy_pct: number | null;
    /** Producer minus consumer; positive is pressure that has not arrived yet. */
    ppi_cpi_gap_pct: number | null;
    unemployment_pct: number | null;
    gdp_pct: number | null;
  };
  fx: {
    usdtry: number | null;
    eurtry: number | null;
    change_1m_pct: number | null;
    change_3m_pct: number | null;
    change_12m_pct: number | null;
    /** Policy rate minus the twelve-month depreciation — an indication, not a return. */
    carry_12m_pct: number | null;
    series_points: number;
  };
  /** Null without an EVDS key: the pace inside the year is then unmeasured. */
  prices: {
    month: string | null;
    mom_pct: number | null;
    three_month_annualized_pct: number | null;
  } | null;
  /** Null when the KAP tape did not answer; a zero count is a calm week. */
  measures: {
    window_days: number;
    total: number;
    by_kind: Record<string, number>;
    tickers: string[];
    latest_day: string | null;
  } | null;
  not_measured: string[];
}

/** `facts` is null when the policy rate or the inflation print could not be read. */
export interface BistMacroNoteResponse {
  facts: BistMacroFacts | null;
  note: AiNote;
}

export async function fetchBistMacroNote(): Promise<BistMacroNoteResponse> {
  return apiFetch<BistMacroNoteResponse>('/api/bist/macro-note', { anonymous: true });
}

// ── KAP ────────────────────────────────────────────────────────────────────

/**
 * How consequential a class of filing is, computed in Python from the form KAP
 * filed it on. Never a forecast: `high` says the filing changes the company's
 * capital, ownership or earnings, not that the share is expected to move.
 *
 * `unclassified` is the absence of a reading, not a fourth level below
 * `routine`. KAP's free-text forms are named "Özel Durum Açıklaması (Genel)"
 * whatever they contain, so a band on one would be a guess — and a merger drawn
 * as routine is worse than a merger drawn as unread.
 */
export type BistDisclosureBand = 'high' | 'medium' | 'routine' | 'unclassified';

export interface BistDisclosure {
  index: number;
  title: string;
  company: string;
  ticker: string;
  category: string;
  category_label: string;
  published_at: string | null;
  summary: string;
  is_late: boolean;
  url: string;
  /** Stable key for the event class. Switch on this, never on `event_label`. */
  event: string;
  /** Turkish, short enough for a chip on a dense row. */
  event_label: string;
  /**
   * 1-10, or null for a filing that could not be classified.
   *
   * Ordering, not measurement — nobody measured a merger against a buyback, and
   * the scale claims only that the two are not the same size. It drives the
   * bar's length and the band is derived from it, so the two cannot disagree.
   * Null rather than 0: zero is the bottom of the scale, and an unclassified
   * filing was never placed on it.
   */
  score: number | null;
  band: BistDisclosureBand;
}

export interface BistKapResponse {
  limit: number;
  ticker: string | null;
  categories: string[];
  count: number;
  /**
   * KAP is currently refusing this address.
   *
   * The tape still answers — from the buffer — but it is not catching up, so a
   * short list means "blocked" rather than "quiet". The board has no other way
   * to tell those apart.
   */
  rate_limited: boolean;
  disclosures: BistDisclosure[];
}

export interface BistKapQuery {
  limit?: number;
  ticker?: string;
  /** Comma-separated categories; `"all"` includes fund housekeeping. */
  categories?: string;
}

export async function fetchBistKap(query: BistKapQuery = {}): Promise<BistKapResponse> {
  return apiFetch<BistKapResponse>('/api/bist/kap', {
    params: { ...query },
    anonymous: true,
  });
}

/**
 * One filing, read by the model.
 *
 * The disclosure travels back with the note rather than being taken from the
 * row the reader clicked. The two are the same object today, but the note is
 * written *about* what this endpoint returned, and pairing prose with a
 * different copy of the filing is how a summary and the sentence explaining it
 * drift apart.
 */
export interface BistKapNoteResponse {
  disclosure: BistDisclosure;
  note: AiNote;
}

export async function fetchBistKapNote(index: number): Promise<BistKapNoteResponse> {
  return apiFetch<BistKapNoteResponse>(`/api/bist/kap/${index}/note`, { anonymous: true });
}

export interface BistRestrictionsResponse {
  count: number;
  source: string;
  restrictions: BistDisclosure[];
}

export async function fetchBistRestrictions(limit: number = 30): Promise<BistRestrictionsResponse> {
  return apiFetch<BistRestrictionsResponse>('/api/bist/restrictions', {
    params: { limit },
    anonymous: true,
  });
}

// ── VİOP ───────────────────────────────────────────────────────────────────

export interface ViopContract {
  contract: string;
  underlying: string;
  expiry: string;
  /**
   * `expiry` as an ISO day, or null when the label could not be read.
   *
   * The exchange writes `31 Ağu 26`, which sorts alphabetically into a term
   * structure that does not exist — Ekim lands before Eylül. The curve and the
   * expiry split both order contracts by time, so both read this and drop the
   * rows that have none rather than falling back to the label.
   */
  expiry_date: string | null;
  /**
   * `future`, `call` or `put`.
   *
   * The board is not one instrument. A put on the same underlying and expiry
   * settles at its premium — 0.13 where the future settles at 13.16 — so the
   * two cannot share an axis or a total, and every panel on the page reads
   * futures only.
   */
  kind: 'future' | 'call' | 'put';
  /** `FIZ.` — settles in shares rather than in cash. */
  physical: boolean;
  last: number | null;
  change_pct: number | null;
  high: number | null;
  low: number | null;
  open_interest: number | null;
  open_interest_change: number | null;
  settlement: number | null;
  previous_settlement: number | null;
  traded_at: string;
}

export interface ViopUnderlying {
  underlying: string;
  open_interest: number;
  change: number;
  contracts: number;
}

export interface BistViopResponse {
  as_of: string;
  stale: boolean;
  count: number;
  summary: { total_open_interest: number; by_underlying: ViopUnderlying[] };
  contracts: ViopContract[];
}

export async function fetchBistViop(underlying?: string): Promise<BistViopResponse> {
  return apiFetch<BistViopResponse>('/api/bist/viop', {
    params: { underlying },
    anonymous: true,
  });
}

/** The quadrant carrying most of the day's open-interest movement. */
export type BistViopStance =
  | 'long_build'
  | 'short_build'
  | 'short_cover'
  | 'long_liquidation'
  | 'mixed';

export type BistViopCurveShape = 'contango' | 'backwardation' | 'flat';

/** One underlying's share of everything outstanding on the board. */
export interface BistViopConcentrationEntry {
  underlying: string;
  open_interest: number | null;
  share_pct: number | null;
  oi_change_pct: number | null;
  expiries: number;
}

export interface BistViopMover {
  underlying: string;
  expiry: string;
  quadrant: string;
  oi_change_pct: number | null;
  change_pct: number | null;
  open_interest: number | null;
}

export interface BistViopCurve {
  underlying: string;
  shape: BistViopCurveShape;
  spread_pct: number | null;
  expiries: number;
  front: string;
  back: string;
}

/**
 * Every figure here is already in **percentage points**, not a fraction.
 *
 * The backend quantizes each reading before it fingerprints the note, and the
 * paragraph beside the header is rendered from those same bucketed values — so
 * these go through `formatPoints`, never `formatPercent`. See the header of
 * `lib/bist-market-note.ts`.
 */
export interface BistViopFacts {
  stance: BistViopStance;
  as_of: string | null;
  stale: boolean;
  board: {
    contracts: number;
    underlyings: number;
    /** Contracts that published an open-interest figure. */
    measured: number;
    /** Contracts that published none — an unread column, not a position of zero. */
    silent: number;
    /** Contracts whose expiry label could not be dated, and so carry no time axis. */
    undated: number;
    total_open_interest: number | null;
    open_interest_change: number | null;
    growth_pct: number | null;
    physical_pct: number | null;
  };
  concentration: {
    top: BistViopConcentrationEntry[];
    top_share_pct: number | null;
    /** One underlying holds most of the book, so a board-wide figure is its figure. */
    concentrated: boolean;
  };
  quadrants: {
    counts: Record<string, number>;
    /** Share of the day's open-interest movement, which is not the share of contracts. */
    weight_pct: Record<string, number | null>;
    /** Contracts where open interest or price did not move, so they name no one. */
    on_axis: number;
    measured: number;
  };
  movers: BistViopMover[];
  curves: BistViopCurve[];
  roll: {
    front: string | null;
    front_share_pct: number | null;
    expiries: number;
  };
  not_measured: string[];
}

/**
 * `facts` is null when the board could not be read or came back too thin.
 *
 * This source is a scrape, so silence is far more often an outage than a quiet
 * session, and the panel must not render it as one.
 */
export interface BistViopNoteResponse {
  facts: BistViopFacts | null;
  note: AiNote;
}

export async function fetchBistViopNote(): Promise<BistViopNoteResponse> {
  return apiFetch<BistViopNoteResponse>('/api/bist/viop-note', { anonymous: true });
}

// ── VİOP teminat tarama bantları ──────────────────────────────────────────

/**
 * `[column, bin, longTry, shortTry]` — what stood on one price bin at the close
 * of one session.
 *
 * A snapshot, not an event: a level surviving ten sessions appears in ten
 * cells. That repetition is what draws the horizontal streak across the map,
 * and what makes the session price finally sweeps a level read as the streak
 * stopping dead.
 */
export type ViopMarginCell = [number, number, number, number];

export interface ViopMapGrid {
  price_min: number;
  price_max: number;
  bin_size: number;
  bins: number;
}

export interface ViopMapSession {
  day: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
}

export interface ViopVolumeProfile {
  /** One figure per bin, indexed against the same grid as `levels`. */
  bins: number[];
  total: number;
  bars: number;
  interval: string;
  from: string | null;
  to: string | null;
}

export interface ViopMapModel {
  /** Takasbank's scan range as a **fraction** — `0.134` is %13,4. */
  psr: number;
  psr_source: string;
  psr_as_of: string;
  psr_run: string;
  psr_file: string;
  /**
   * Always null, and present on purpose.
   *
   * Takasbank publishes no maintenance margin rate for VİOP, so the price a
   * margin call actually triggers at cannot be computed. The field is named
   * rather than omitted so the page can say why it draws no call level.
   */
  maintenance_margin_rate: null;
  maintenance_source: string;
  contract_multiplier: number;
  direction_rule: string;
  /** Sessions whose settlement did not move, so no side could be assigned. */
  undirected_sessions: number;
  undirected_notional: number;
  basis_adjusted: boolean;
  basis_carried_sessions: number;
  dropped_sessions: number;
  sessions_covered: number;
  sessions_requested: number;
}

export interface BistViopMapResponse {
  ticker: string;
  symbol: string;
  as_of: string | null;
  stale: boolean;
  delay_minutes: number;
  thin: boolean;
  sessions: ViopMapSession[];
  grid: ViopMapGrid;
  cells: ViopMarginCell[];
  /** Strongest cell on the board, which the colour ramp normalises against. */
  max_value: number;
  volume_profile: ViopVolumeProfile | null;
  expiries: string[];
  open_interest: number;
  model: ViopMapModel;
  warnings: string[];
}

export interface ViopMapUnderlying {
  ticker: string;
  volume_try: number;
  open_interest: number;
  expiries: number;
  thin: boolean;
}

export interface BistViopUnderlyingsResponse {
  as_of: string;
  sessions_held: number;
  count: number;
  underlyings: ViopMapUnderlying[];
  /** What the picker opens with — derived from the newest session, not fixed. */
  default: string[];
}

export async function fetchBistViopUnderlyings(): Promise<BistViopUnderlyingsResponse> {
  return apiFetch<BistViopUnderlyingsResponse>('/api/bist/viop-map/underlyings', {
    anonymous: true,
  });
}

export async function fetchBistViopMap(
  ticker: string,
  sessions: number = 120
): Promise<BistViopMapResponse> {
  return apiFetch<BistViopMapResponse>(`/api/bist/viop-map/${encodeURIComponent(ticker)}`, {
    params: { sessions },
    anonymous: true,
  });
}

export type BistViopMapStance = 'long_heavy' | 'short_heavy' | 'balanced' | 'empty';

/** One surviving level: a spot price, its distance from the latest close, what stands on it. */
export interface BistViopMapLevel {
  price: number;
  /** Percentage points from the latest spot close; negative is below it. */
  distance_pct: number | null;
  notional_try: number | null;
}

/**
 * The field as a set of readings. Percentages are already points, bucketed
 * server-side; prices are spot prices on the map's own axis.
 */
export interface BistViopMapFacts {
  stance: BistViopMapStance;
  ticker: string;
  /** The newest session in the window. */
  as_of: string;
  stale: boolean;
  window: {
    requested: number;
    covered: number;
    undirected_sessions: number;
    undirected_try: number | null;
    basis_carried_sessions: number;
    dropped_sessions: number;
  };
  band: {
    psr_pct: number | null;
    rungs_pct: (number | null)[];
    as_of: string;
    run: string;
  };
  book: {
    open_interest: number | null;
    expiries: number;
    /** What has not been traded through, on the newest column. */
    standing_try: number | null;
    long_try: number | null;
    short_try: number | null;
    long_share_pct: number | null;
  };
  spot: { close: number };
  /** Heaviest surviving levels per side, nearest first. */
  levels: { long: BistViopMapLevel[]; short: BistViopMapLevel[] };
  session: {
    day: string;
    opened_long_try: number | null;
    opened_short_try: number | null;
    undirected_try: number | null;
    closed_try: number | null;
    oi_change: number | null;
    front_settlement_change_pct: number | null;
  } | null;
  not_measured: string[];
}

/**
 * `facts` is null when the book is too thin to draw or an upstream did not
 * answer — the page has already declined the field on its own by then.
 */
export interface BistViopMapNoteResponse {
  facts: BistViopMapFacts | null;
  note: AiNote;
}

export async function fetchBistViopMapNote(
  ticker: string,
  sessions: number = 120
): Promise<BistViopMapNoteResponse> {
  return apiFetch<BistViopMapNoteResponse>(
    `/api/bist/viop-map/${encodeURIComponent(ticker)}/note`,
    { params: { sessions }, anonymous: true }
  );
}

// ── Calendar ───────────────────────────────────────────────────────────────

export interface BistCalendarEvent {
  kind: 'earnings' | 'dividend';
  day: string;
  ticker: string;
  symbol: string;
  name: string;
  sector: string;
  market_cap: number | null;
  amount: number | null;
  yield_pct: number | null;
}

export interface BistCalendarResponse {
  as_of: string;
  window: { days_back: number; days_ahead: number };
  count: number;
  /** What this calendar covers, stated by the API rather than assumed. */
  covers: string[];
  /** And what it does not — rights and bonus issues have no structured date. */
  excludes: string[];
  days: { day: string; count: number; events: BistCalendarEvent[] }[];
}

export async function fetchBistCalendar(
  daysAhead: number = 90,
  daysBack: number = 14
): Promise<BistCalendarResponse> {
  return apiFetch<BistCalendarResponse>('/api/bist/calendar', {
    params: { days_ahead: daysAhead, days_back: daysBack },
    anonymous: true,
  });
}

// ── Positioning ────────────────────────────────────────────────────────────

export interface BistPositioningRow {
  ticker: string;
  symbol: string;
  name: string;
  sector: string;
  price: number | null;
  change_pct: number | null;
  market_cap: number | null;
  free_float_pct: number | null;
  relative_volume: number | null;
  /** 0.0 at the 52-week low, 1.0 at the high. */
  range_position: number | null;
  beta: number | null;
  rsi: number | null;
  open_interest: number | null;
  open_interest_change: number | null;
  /** Unusual volume against a tight float. Null when the inputs make it meaningless. */
  crowding: number | null;
}

export interface BistPositioningResponse {
  as_of: string;
  stale: boolean;
  delay_minutes: number;
  has_futures_data: boolean;
  crowded: BistPositioningRow[];
  futures: BistPositioningRow[];
}

export async function fetchBistPositioning(limit: number = 50): Promise<BistPositioningResponse> {
  return apiFetch<BistPositioningResponse>('/api/bist/positioning', {
    params: { limit },
    anonymous: true,
  });
}

/**
 * Whether the busiest names sit higher or lower in their own year than the board.
 *
 * Computed on the server before the model saw it. The panel prints the label and
 * the model explains it — the same split every AI surface here uses.
 */
export type BistPositioningStance = 'chasing_strength' | 'bottom_fishing' | 'dispersed';

export interface BistPositioningName {
  ticker: string;
  sector: string;
  crowding: number | null;
  free_float_pct: number | null;
  relative_volume: number | null;
  change_pct: number | null;
  range_pct: number | null;
  rsi: number | null;
}

export interface BistPositioningSector {
  sector: string;
  count: number;
  /** This sector's share of the board's whole crowding score. */
  share_pct: number | null;
  median_relative_volume: number | null;
  median_range_pct: number | null;
}

/**
 * Every figure here is already in percentage points, not a fraction.
 *
 * The backend quantizes each reading before it fingerprints the note, and the
 * paragraph beside the header is rendered from those same bucketed values — so
 * these go through `formatPoints`, never `formatPercent`. See the header of
 * `lib/bist-market-note.ts`.
 */
export interface BistPositioningFacts {
  stance: BistPositioningStance;
  as_of: string | null;
  stale: boolean;
  board: {
    total: number;
    scored: number;
    scored_pct: number | null;
    /** Refused a score because their float is too small to divide by. */
    unscored_tight_float: number;
    /** Refused a score because volume is not elevated at all. */
    unscored_quiet: number;
    median_free_float_pct: number | null;
    median_relative_volume: number | null;
    hot_pct: number | null;
    min_free_float_pct: number | null;
    min_relative_volume: number;
  };
  crowd: {
    cohort: number;
    median_crowding: number | null;
    median_free_float_pct: number | null;
    median_relative_volume: number | null;
    median_range_pct: number | null;
    board_median_range_pct: number | null;
    range_gap_pct: number | null;
    names: BistPositioningName[];
  };
  range: {
    measured: number;
    median_pct: number | null;
    near_high_pct: number | null;
    near_low_pct: number | null;
    near_extreme_pct: number;
    median_rsi: number | null;
    near_high_median_rsi: number | null;
    overbought_pct: number | null;
    oversold_pct: number | null;
  };
  sectors: BistPositioningSector[];
  sector_concentrated: boolean;
  /** Null when VİOP could not be read — published positioning is then missing. */
  futures: {
    covered: number;
    total_open_interest: number | null;
    growth_pct: number | null;
    quadrants: Record<string, number>;
    dominant: string | null;
    movers: {
      ticker: string;
      quadrant: string | null;
      oi_change_pct: number | null;
      change_pct: number | null;
    }[];
  } | null;
  /** Readings this board deliberately does not carry, named rather than implied. */
  not_measured: string[];
}

/**
 * `facts` is null when the board could not be read or is too thin to describe.
 *
 * Not the same as a quiet market, and the panel must not render it as one.
 */
export interface BistPositioningNoteResponse {
  facts: BistPositioningFacts | null;
  note: AiNote;
}

export async function fetchBistPositioningNote(): Promise<BistPositioningNoteResponse> {
  return apiFetch<BistPositioningNoteResponse>('/api/bist/positioning-note', {
    anonymous: true,
  });
}

// ── Gece Mesaisi Endeksi ───────────────────────────────────────────────────

export type NightShiftStatus =
  | 'quiet'
  | 'normal'
  | 'elevated'
  | 'spike'
  | 'insufficient_data'
  | 'unavailable';

/** One day of a source's own trend, on the grid `NightShift.history` defines. */
export interface NightShiftDay {
  day: string;
  /** Null where the day could not be scored — the slot is kept, not closed. */
  ratio: number | null;
}

/** One input to the index, with the figure it was scored from. */
export interface NightShiftSource {
  key: string;
  name: string;
  value: number;
  baseline: number;
  /** Multiple of its own usual. Null when the baseline was too small to divide by. */
  ratio: number | null;
  /** What was measured, in the units it was measured in. */
  detail: string;
  history: NightShiftDay[];
}

/** One day of the shared trend, scored by the same rules as the headline. */
export interface NightShiftHistoryDay {
  day: string;
  index: number | null;
  sources_used: number;
}

/**
 * Gece Mesaisi Endeksi — the BIST realm's counterpart to the Pentagon Pizza
 * Index.
 *
 * `index` is a multiple of usual legislative activity, not a 0–100 score, and
 * the UI renders it that way on purpose — see `lib/night-shift.ts`.
 */
export interface NightShift {
  index: number | null;
  status: NightShiftStatus;
  label: string;
  sources_used: number;
  sources_total: number;
  sources: NightShiftSource[];
  history: NightShiftHistoryDay[];
  /** ISO date of the most recent extra edition of the Resmî Gazete. */
  last_mukerrer: string | null;
  days_since_mukerrer: number | null;
  mukerrer_today: boolean;
  as_of: string;
  /** True when replayed from cache after the sources could not be reached. */
  stale: boolean;
  source: string;
  source_url: string;
}

/**
 * Never answers an error. Like `/api/macro/pizza-index`, a failed read of a
 * novelty gauge must not surface as a page-level failure — the outage arrives
 * as `status: 'unavailable'` in an otherwise normal payload.
 */
export async function fetchBistNightShift(): Promise<NightShift> {
  return apiFetch<NightShift>('/api/bist/night-shift', { anonymous: true });
}

// ── Ownership ──────────────────────────────────────────────────────────────

export type BistHolderCategory = 'holding' | 'state' | 'foreign' | 'fund' | 'other';

export type BistOwnershipSourceKind = 'isyatirim_shareholders' | 'kap_fund_report';

/**
 * How a lira value on this board was arrived at.
 *
 * `marked` is a stake times today's market cap; `reported` is the figure the
 * fund itself filed. They are not the same kind of number and the table says
 * which one each row is, rather than mixing them in one column silently.
 */
export type BistOwnershipValueBasis = 'marked' | 'reported' | 'unknown';

export interface BistOwnershipSource {
  kind: BistOwnershipSourceKind;
  label: string;
  url: string | null;
  /** What date the figure describes — for a fund, the report month. */
  as_of: string | null;
  retrieved_at: string | null;
}

export interface BistOwnershipPosition {
  ticker: string;
  name: string;
  /** Share of the company's capital, in percent. `null` when unknown. */
  stake_pct: number | null;
  value_try: number | null;
  value_basis: BistOwnershipValueBasis;
  /** Share of the holder's *known* lira value. `null` when nothing is valued. */
  weight_pct: number | null;
  source: BistOwnershipSource;
  note: string | null;
  /**
   * Earliest daily snapshot the holder appears in. With `at_baseline` true it
   * means "since at least" — the real entry predates the first snapshot and
   * is unknown, and the page must not print it as an entry date.
   */
  since: string | null;
  at_baseline: boolean;
  /** The stake on the previous snapshot, as a fraction. Null with one snapshot. */
  previous_stake_pct: number | null;
  /** `stake_pct - previous_stake_pct`, in fraction points. Null when unknown. */
  delta_pct: number | null;
}

export type BistStakeMoveKind = 'new' | 'exit' | 'add' | 'trim';

/**
 * A holder entering, leaving or resizing, read off two daily snapshots of the
 * shareholder table. `observed_at` is the snapshot day the change was first
 * seen — the card lags the filing, and this is not the filing date.
 */
export interface BistStakeMove {
  id: string;
  ticker: string;
  company: string;
  holder: string;
  entity_id: string | null;
  kind: BistStakeMoveKind;
  stake_before: number | null;
  stake_after: number | null;
  delta_pct: number | null;
  observed_at: string;
}

export interface BistOwnershipSlice {
  key: string;
  label: string;
  ticker: string | null;
  value_try: number;
  pct: number;
}

/** An ownership-shaped KAP filing: insider trade, block sale, tender offer, capital action. */
export interface BistOwnershipMove {
  id: string;
  ticker: string;
  company: string;
  event: string;
  event_label: string;
  headline: string;
  published_at: string | null;
  url: string;
  score: number | null;
  band: BistDisclosureBand;
}

export interface BistOwnershipSourceHealth {
  kind: BistOwnershipSourceKind;
  ok: boolean;
  entities_covered: number;
  tickers_covered: number;
  as_of: string | null;
  message: string | null;
}

export interface BistOwnershipEntity {
  id: string;
  name: string;
  subtitle: string | null;
  category: BistHolderCategory;
  /** Sum of what could be valued. `null` when nothing could. */
  total_value_try: number | null;
  positions_count: number;
  allocation: BistOwnershipSlice[];
  top_positions: BistOwnershipPosition[];
  last_move: BistOwnershipMove | null;
  as_of: string | null;
  stale: boolean;
  issues: string[];
  has_data: boolean;
  /** What the figures do and do not cover, under every allocation bar. */
  coverage_note: string | null;
}

export interface BistOwnershipEntityDetail {
  entity: BistOwnershipEntity;
  positions: BistOwnershipPosition[];
  moves: BistOwnershipMove[];
  stake_moves: BistStakeMove[];
  sources: BistOwnershipSource[];
  /** The oldest snapshot day. Nothing before it is known. */
  tracking_since: string | null;
}

export interface BistOwnershipBoard {
  entities: BistOwnershipEntity[];
  latest_moves: BistOwnershipMove[];
  latest_stake_moves: BistStakeMove[];
  tracking_since: string | null;
  category_counts: Record<string, number>;
  sources: BistOwnershipSourceHealth[];
  /** The index the cards were fetched for — `XU100`. */
  universe: string;
  tickers_covered: number;
  tickers_total: number;
  as_of: string | null;
  last_refresh_at: string | null;
  stale: boolean;
}

/** Never 503 on a missing board is a lie this route refuses to tell: it 503s. */
export async function fetchBistOwnershipBoard(): Promise<BistOwnershipBoard> {
  return apiFetch<BistOwnershipBoard>('/api/bist/ownership/board', { anonymous: true });
}

export async function fetchBistOwnershipEntity(
  entityId: string
): Promise<BistOwnershipEntityDetail> {
  return apiFetch<BistOwnershipEntityDetail>(
    `/api/bist/ownership/entities/${encodeURIComponent(entityId)}`,
    { anonymous: true }
  );
}

export async function fetchBistOwnershipMoves(
  limit: number = 20,
  ticker?: string
): Promise<BistOwnershipMove[]> {
  return apiFetch<BistOwnershipMove[]>('/api/bist/ownership/moves', {
    params: { limit, ticker },
    anonymous: true,
  });
}

/** One row of a company's shareholder table, as İş Yatırım prints it. */
export interface BistOwnershipHolder {
  label: string;
  stake_pct: number;
  value_try: number | null;
  entity_id: string | null;
  /**
   * Whether the row matched a tracked holder. Untracked rows are still listed
   * — the reader is owed every ≥5% holder, not only the ones the board names.
   */
  tracked: boolean;
  since: string | null;
  at_baseline: boolean;
  previous_stake_pct: number | null;
  delta_pct: number | null;
}

export interface BistOwnershipFundHolder {
  entity_id: string;
  name: string;
  code: string;
  /** Share of the fund's equity book, in percent. */
  weight_in_fund_pct: number | null;
  value_try: number | null;
  stake_pct: number | null;
  as_of: string | null;
  url: string | null;
}

export interface BistAssetOwners {
  ticker: string;
  name: string;
  market_cap: number | null;
  free_float_pct: number | null;
  /** Foreign investors' share of the free float, via Takasbank custody. */
  foreign_ratio_pct: number | null;
  holders: BistOwnershipHolder[];
  funds: BistOwnershipFundHolder[];
  moves: BistOwnershipMove[];
  stake_moves: BistStakeMove[];
  tracking_since: string | null;
  as_of: string | null;
  stale: boolean;
  source_url: string | null;
}

export type BistOwnershipStance =
  | 'state_anchored'
  | 'family_holdings'
  | 'foreign_strategic'
  | 'dispersed';

export interface BistOwnershipFacts {
  stance: BistOwnershipStance;
  coverage: {
    universe: string;
    tickers_covered: number;
    tickers_total: number;
    entities: number;
    entities_with_data: number;
    as_of: string | null;
    tracking_since: string | null;
    tracking_days: number;
  };
  total: {
    /** Billions of lira, to the nearest ten. Null when nothing could be valued. */
    valued_try_bn: number | null;
    categories: { category: BistHolderCategory; share_pct: number | null; entities: number }[];
  };
  holders: {
    top: {
      name: string;
      category: BistHolderCategory;
      value_try_bn: number | null;
      positions: number;
      share_pct: number | null;
    }[];
    top3_share_pct: number | null;
  };
  companies: {
    with_named_holder: number;
    without_named_holder: number;
    majority_held: number;
    /** These four are in percent, not fractions — the note's facts are day-quantized readings, not API rows. */
    median_named_stake_pct: number | null;
    median_free_float_pct: number | null;
    median_foreign_ratio_pct: number | null;
    foreign_high: { ticker: string; pct: number | null }[];
    foreign_low: { ticker: string; pct: number | null }[];
  };
  moves: {
    stake_total: number;
    stake_kinds: Record<string, number>;
    recent_stakes: {
      ticker: string;
      holder: string;
      kind: BistStakeMoveKind;
      before_pct: number | null;
      after_pct: number | null;
      observed_at: string;
    }[];
    filing_kinds: Record<string, number>;
    recent_filings: { ticker: string; event: string; day: string }[];
  };
  funds: { tracked: number; readable: number };
  not_measured: string[];
  stale: boolean;
}

export interface BistOwnershipNoteResponse {
  facts: BistOwnershipFacts | null;
  note: AiNote;
}

export async function fetchBistOwnershipNote(): Promise<BistOwnershipNoteResponse> {
  return apiFetch<BistOwnershipNoteResponse>('/api/bist/ownership/note', { anonymous: true });
}

/**
 * 404 outside the XU100, with a message saying so. "Not covered" and "nobody
 * above 5%" are different answers and the panel tells them apart by status.
 */
export async function fetchBistAssetOwners(ticker: string): Promise<BistAssetOwners> {
  return apiFetch<BistAssetOwners>(`/api/bist/ownership/assets/${encodeURIComponent(ticker)}`, {
    anonymous: true,
  });
}

// ── Radar ──────────────────────────────────────────────────────────────────

export type RadarHorizon = 'short' | 'swing' | 'position';

export const RADAR_HORIZONS: { value: RadarHorizon; label: string }[] = [
  { value: 'short', label: 'Kısa' },
  { value: 'swing', label: 'Swing' },
  { value: 'position', label: 'Pozisyon' },
];

/** A key and the Turkish chip text the server computed for it. */
export interface RadarLabelled {
  key: string;
  label: string;
}

export interface RadarLevels {
  entry_low: number;
  entry_high: number;
  entry_mid: number;
  stop: number;
  target1: number;
  target2: number | null;
  rr: number;
  atr: number;
  price: number;
  /** Fraction below the 20-bar high. */
  pullback_pct: number;
  rsi: number;
  rsi_divergence: string | null;
  /** Last five bars' mean volume over the twenty before; <1 is a quiet pullback. */
  volume_ratio: number | null;
  structure: 'higher' | 'lower' | 'mixed' | null;
  zone_touches: number;
  zone_source: 'support_zone' | 'moving_average';
  range_position: number | null;
  ema_fast: number;
  ema_slow: number;
  high20: number;
  sma50_gap: number | null;
}

export interface RadarFundamentals {
  layout: 'industrial' | 'bank' | 'insurance' | null;
  latest_period: string | null;
  quarters: number;
  inflation: number | null;
  roe: number | null;
  real_revenue_growth: number | null;
  real_profit_growth: number | null;
  net_debt_ebitda: number | null;
  short_debt_share: number | null;
  loss_quarters: number | null;
  cash_conversion: number | null;
  equity: number | null;
}

export interface RadarStreet {
  gap_pct: number;
  mark: number | null;
  analysts: number;
}

export type RadarStance = 'bullish' | 'bearish' | 'neutral';

/** How often a commentator's graded calls landed. Shrunk toward 50% for small samples. */
export interface RadarVoiceAccuracy {
  hits: number;
  misses: number;
  flats: number;
  pending: number;
  n: number;
  raw: number | null;
  shrunk: number;
}

/** One recent call by a followed commentator on this name. */
export interface RadarVoice {
  voice_id: string;
  voice_name: string;
  stance: RadarStance;
  said_at: string;
  horizon_days: number;
  target: number | null;
  /** Verbatim from the captions; empty when the model's quote could not be verified. */
  quote: string;
  video_title: string;
  url: string;
  outcome: { result: 'hit' | 'miss' | 'flat'; excess: number } | null;
  accuracy: RadarVoiceAccuracy | null;
}

export interface RadarVoicesReport {
  checked: boolean;
  voices: number;
  videos: number;
  transcripts: number;
  extractions: number;
  graded: number;
  failures: string[];
}

export type RadarStage = 'gate' | 'technical' | 'scored' | 'candidate';

/** Every XU100 member, wherever it stopped in the funnel. */
export interface RadarRow {
  ticker: string;
  symbol: string;
  name: string;
  sector: string;
  sector_class: string;
  price: number | null;
  change_pct: number | null;
  market_cap: number | null;
  score_technical: number | null;
  score_fundamental: number | null;
  /** Share of the fundamental weight that had data behind it, 0..1. */
  fundamental_coverage: number;
  fundamental_depth: 'full' | 'ratios_only';
  score_total: number | null;
  rr: number | null;
  vetoes: RadarLabelled[];
  stage_reached: RadarStage;
  rejected_reason: string | null;
  rejected_label: string | null;
}

export interface RadarCandidate extends RadarRow {
  pe: number | null;
  pb: number | null;
  ev_ebitda: number | null;
  week52_high: number | null;
  week52_low: number | null;
  next_earnings: string | null;
  levels: RadarLevels;
  fundamentals: RadarFundamentals;
  adjustments: { key: string; label: string; points: number }[];
  flags: RadarLabelled[];
  street: RadarStreet | null;
  kap_checked: boolean;
  memo: AiNote | null;
  /** Recent calls by the followed commentators on this name, newest first. */
  voices: RadarVoice[];
}

export interface RadarResult {
  horizon: RadarHorizon;
  horizon_label: string;
  scanned_at: string;
  duration_seconds: number | null;
  delay_minutes: number;
  universe_size: number;
  fundamental_depth: 'full' | 'partial' | 'ratios_only';
  fundamentals_covered: number;
  kap_checked: boolean;
  inflation_yoy: number | null;
  counts: { gate_passed: number; technical_passed: number; vetoed: number; candidates: number };
  memos: { done: number; total: number };
  /** Absent on results persisted before the commentator step existed. */
  voices_report?: RadarVoicesReport;
  candidates: RadarCandidate[];
  nearest: RadarRow[];
  universe: RadarRow[];
}

/** What a running scan publishes before the scores exist. */
export interface RadarProgress {
  progress: { stage: string; done: number; total: number };
}

export type RadarJobStatus = 'queued' | 'running' | 'done' | 'error';

export interface RadarJob {
  jobId: string;
  horizon: RadarHorizon;
  status: RadarJobStatus;
  stage: string | null;
  stageIndex: number;
  stages: { key: string; label: string }[];
  elapsedSeconds: number;
  /** The scan result once scoring has run, or `null`. */
  result: RadarResult | null;
  /** Per-ticker progress while technical or fundamentals are running. */
  progress: RadarProgress['progress'] | null;
  error: string | null;
}

interface RawRadarJob {
  job_id: string;
  key: string;
  status: string;
  stage?: string | null;
  stage_index?: number;
  stages?: { key: string; label: string }[];
  elapsed_seconds?: number;
  result?: RadarResult | null;
  partial_result?: (RadarResult | RadarProgress) | null;
  error?: string | null;
}

function isProgress(value: unknown): value is RadarProgress {
  return !!value && typeof value === 'object' && 'progress' in (value as object);
}

export function toRadarJob(raw: RawRadarJob): RadarJob {
  const partial = raw.partial_result ?? null;
  const result = raw.result ?? (partial && !isProgress(partial) ? partial : null);
  return {
    jobId: raw.job_id,
    horizon: (raw.key.split(':')[1] ?? 'swing') as RadarHorizon,
    status: raw.status as RadarJobStatus,
    stage: raw.stage ?? null,
    stageIndex: raw.stage_index ?? 0,
    stages: raw.stages ?? [],
    elapsedSeconds: raw.elapsed_seconds ?? 0,
    result,
    progress: isProgress(partial) ? partial.progress : null,
    error: raw.error ?? null,
  };
}

export async function fetchBistRadar(horizon: RadarHorizon): Promise<RadarResult> {
  return apiFetch<RadarResult>('/api/bist/radar', { params: { horizon }, anonymous: true });
}

export async function startBistRadarScan(horizon: RadarHorizon): Promise<RadarJob> {
  const raw = await apiFetch<RawRadarJob>('/api/bist/radar/scan', {
    method: 'POST',
    params: { horizon },
    anonymous: true,
  });
  return toRadarJob(raw);
}

export async function fetchBistRadarJob(jobId: string): Promise<RadarJob> {
  const raw = await apiFetch<RawRadarJob>(`/api/bist/radar/jobs/${encodeURIComponent(jobId)}`, {
    anonymous: true,
  });
  return toRadarJob(raw);
}

export async function cancelBistRadarScan(jobId: string): Promise<RadarJob> {
  const raw = await apiFetch<RawRadarJob>(`/api/bist/radar/jobs/${encodeURIComponent(jobId)}`, {
    method: 'DELETE',
    anonymous: true,
  });
  return toRadarJob(raw);
}

// ── Financial statements (Bilanço) ──────────────────────────────────────────

/** Which chart of accounts İş Yatırım answered under. Decides what lines exist. */
export type BistLayout = 'industrial' | 'bank' | 'insurance';

/** Why the board could not restate figures into today's lira. */
export type BistDeflationReason = 'cpi_key_missing' | 'cpi_unavailable' | 'cpi_too_short';

/**
 * Every statement line the board can draw.
 *
 * A record rather than named fields: the panels iterate over the field list the
 * API says this company has, and a fixed interface would have to be kept in
 * step with `FIELD_KEYS` in Python by hand.
 */
export type BistStatementValues = Record<string, number | null>;

export interface BistQuarter {
  period: string;
  year: number;
  quarter: number;
  nominal: BistStatementValues;
  /** Null when this quarter predates the price index — never a dict of nulls. */
  real: BistStatementValues | null;
  deflator: number | null;
  /** Restated with the newest published index rather than its own month. */
  provisional: boolean;
}

export interface BistFinancialRatios {
  period: string;
  gross_margin: number | null;
  operating_margin: number | null;
  ebitda_margin: number | null;
  net_margin: number | null;
  current_ratio: number | null;
  short_debt_share: number | null;
  cash_conversion: number | null;
  net_debt_ebitda: number | null;
  roe_ttm: number | null;
}

export interface BistFinancialTtm {
  revenue: number | null;
  ebitda: number | null;
  net_income: number | null;
  real_revenue_growth: number | null;
  real_ebitda_growth: number | null;
  real_net_income_growth: number | null;
  real_equity_growth: number | null;
  nominal_revenue_growth: number | null;
  margin_trend: number | null;
  inflation_yoy: number | null;
  loss_quarters: number | null;
}

export interface BistDeflation {
  available: boolean;
  reason: BistDeflationReason | null;
  base_period: string | null;
  base_month: string | null;
  cpi_latest_month: string | null;
  cpi_series: string;
  provisional_periods: string[];
  uncovered_periods: string[];
}

export interface BistFinancials {
  ticker: string;
  name: string | null;
  sector: string | null;
  layout: BistLayout;
  layout_label: string;
  /** What this chart of accounts can carry at all. */
  layout_fields: string[];
  /** Of those, what this company actually reported. */
  available_fields: string[];
  latest_period: string | null;
  fetched_at: string;
  source_url: string;
  /** Oldest first — charts consume in order. */
  quarters: BistQuarter[];
  ratios: BistFinancialRatios[];
  ttm: BistFinancialTtm;
  deflation: BistDeflation;
  market: {
    price: number | null;
    market_cap: number | null;
    pe: number | null;
    pb: number | null;
    delay_minutes: number;
  } | null;
  stale: boolean;
}

export interface BistFinancialsNoteResponse {
  facts: Record<string, unknown> | null;
  note: AiNote;
}

export async function fetchBistFinancials(
  ticker: string,
  quarters: number = 12
): Promise<BistFinancials> {
  return apiFetch<BistFinancials>(`/api/bist/financials/${encodeURIComponent(ticker)}`, {
    params: { quarters },
    anonymous: true,
  });
}

export async function fetchBistFinancialsNote(ticker: string): Promise<BistFinancialsNoteResponse> {
  return apiFetch<BistFinancialsNoteResponse>(
    `/api/bist/financials/${encodeURIComponent(ticker)}/note`,
    { anonymous: true }
  );
}
