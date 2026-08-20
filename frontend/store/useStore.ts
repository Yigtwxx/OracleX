import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface NewsItem {
  id: string;
  title: string;
  summary: string;
  source: string;
  published_at: string;
  /**
   * Undefined when the headline could not be attributed to an asset. Plenty
   * of real market news is not about one ticker, and the backend no longer
   * defaults those to BTC just to fill the field.
   */
  symbol?: string;
  asset_type: 'stock' | 'crypto';
  url?: string;
}

/**
 * Levels computed by the backend from real OHLCV. Every field is optional
 * because a genuinely thin market may yield some indicators and not others,
 * and the panel says so rather than showing a placeholder in their place.
 */
/** RSI on one timeframe: the level, and which way it is going. */
export interface RsiRead {
  value?: number | null;
  signal?: string | null;
  period?: number;
  change_5_bars?: number | null;
  slope?: 'rising' | 'falling' | 'flat' | null;
  divergence?: string | null;
}

/** One chart of the same asset, read on its own terms. */
export interface TimeframeRead {
  timeframe: string;
  horizon: 'short' | 'medium' | 'long' | string;
  bars?: number;
  covers_days?: number | null;
  trend?: string | null;
  atr?: number | null;
  atr_percent?: number | null;
  rsi?: RsiRead;
}

/**
 * A band price reversed in — never a single level.
 *
 * Both bounds are sent because both were measured. Rendering only `mid` would
 * put back the false precision the backend removed when it stopped quoting
 * support as one decimal.
 */
export interface PriceZone {
  low: number;
  high: number;
  mid: number;
  touches: number;
  flip: boolean;
  /** 0-100: how often, how recently, on what volume, and whether it flipped. */
  strength: number;
  horizon: 'short' | 'medium' | 'long' | string;
  timeframe: string;
  /** Every timeframe that found this band — three agreeing is the strong case. */
  timeframes: string[];
  confluence: string[];
  distance_percent: number;
}

/** Where this price sits in its own multi-year history. */
export interface ChartStructure {
  range_high?: number | null;
  range_low?: number | null;
  range_bars?: number | null;
  range_timeframe?: string | null;
  position_percent?: number | null;
  distance_to_high_percent?: number | null;
  distance_to_low_percent?: number | null;
  sma50?: number | null;
  sma200?: number | null;
  price_vs_sma200_percent?: number | null;
  swing_structure?: string | null;
  timeframe_alignment?: string | null;
}

export interface TechnicalSignals {
  rsi_signal?: string;
  /**
   * Preformatted price bands (`"$61,830 – $63,238"`), nearest first — not
   * numbers, and not single prices: the backend computes support as an area
   * price reversed in across 4h/1d/1w candles. Render as given.
   */
  support_levels?: string[];
  resistance_levels?: string[];
  target_price?: string;

  /**
   * The multi-timeframe read behind those bands. Every field is optional: an
   * analysis stored before this shape existed still parses, and the panel falls
   * back to the preformatted lists above.
   */
  current_price?: number | null;
  primary_timeframe?: string | null;
  timeframes?: TimeframeRead[];
  support_zones?: PriceZone[];
  resistance_zones?: PriceZone[];
  inside_zones?: PriceZone[];
  structure?: ChartStructure | null;
}

export interface SentimentAnalysis {
  sentiment: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  reasoning: string;
  historical_context: string;
  technical_signals?: TechnicalSignals;
  prediction_hash?: string;
  tx_hash?: string;
  /**
   * `'keyword-fallback'` when no model was reachable and the verdict came
   * from counting words in the headline. Absent for a real model analysis.
   */
  source?: string;
}

// Price Alert Types
export interface PriceAlert {
  id: string;
  symbol: string;
  displaySymbol: string;
  targetPrice: number;
  condition: 'above' | 'below';
  isActive: boolean;
  isTriggered: boolean;
  createdAt: string;
}

interface OracleStore {
  // News state
  newsItems: NewsItem[];
  selectedNews: NewsItem | null;
  isLoadingNews: boolean;

  // Chart state
  chartSymbol: string;

  // Recent symbols — last 10 viewed symbols (persisted)
  recentSymbols: string[];

  /**
   * The in-flight analysis job per news item.
   *
   * The analysis itself lives in the React Query cache keyed by news id, not
   * here: a single global `analysis` slot meant a late response for item A
   * overwrote the panel while the user was already reading item B.
   */
  analysisJobIds: Record<string, string>;

  // Current price from chart
  currentPrice: number | null;

  // Price Alerts state
  priceAlerts: PriceAlert[];
  isAlertModalOpen: boolean;

  // Actions
  setNewsItems: (items: NewsItem[]) => void;
  selectNews: (news: NewsItem) => void;
  setChartSymbol: (symbol: string) => void;
  setAnalysisJobId: (newsId: string, jobId: string) => void;
  setLoadingNews: (loading: boolean) => void;
  setCurrentPrice: (price: number) => void;
  clearSelection: () => void;

  // Price Alert Actions
  addAlert: (alert: Omit<PriceAlert, 'id' | 'isActive' | 'isTriggered' | 'createdAt'>) => void;
  removeAlert: (id: string) => void;
  triggerAlert: (id: string) => void;
  toggleAlertModal: (open: boolean) => void;
}

export const useStore = create<OracleStore>()(
  persist(
    (set, get) => ({
      // Initial state
      newsItems: [],
      selectedNews: null,
      isLoadingNews: false,
      chartSymbol: 'BINANCE:BTCUSDT',
      recentSymbols: [],
      analysisJobIds: {},
      currentPrice: null,
      priceAlerts: [],
      isAlertModalOpen: false,

      // Actions - setNewsItems with guaranteed sorted order
      setNewsItems: (items) => {
        const sortedItems = [...items].sort((a, b) => {
          const dateCompare = b.published_at.localeCompare(a.published_at);
          if (dateCompare !== 0) return dateCompare;
          return a.id.localeCompare(b.id);
        });
        set({ newsItems: sortedItems });
      },

      selectNews: (news) =>
        set((state) => {
          // An unattributed item leaves the chart on whatever was already
          // shown, rather than pointing it at an asset the story is not about.
          const updated = news.symbol
            ? [news.symbol, ...state.recentSymbols.filter((s) => s !== news.symbol)].slice(0, 10)
            : state.recentSymbols;
          return {
            selectedNews: news,
            chartSymbol: news.symbol ?? state.chartSymbol,
            recentSymbols: updated,
          };
        }),

      setChartSymbol: (symbol) =>
        set((state) => {
          const updated = [symbol, ...state.recentSymbols.filter((s) => s !== symbol)].slice(0, 10);
          return { chartSymbol: symbol, recentSymbols: updated };
        }),

      setAnalysisJobId: (newsId, jobId) =>
        set((state) => ({
          analysisJobIds: { ...state.analysisJobIds, [newsId]: jobId },
        })),

      setLoadingNews: (loading) => set({ isLoadingNews: loading }),

      setCurrentPrice: (price) => set({ currentPrice: price }),

      clearSelection: () => set({ selectedNews: null }),

      // Price Alert Actions
      addAlert: (alertData) => {
        const newAlert: PriceAlert = {
          ...alertData,
          id: `alert_${Date.now()}`,
          isActive: true,
          isTriggered: false,
          createdAt: new Date().toISOString(),
        };
        set((state) => ({
          priceAlerts: [...state.priceAlerts, newAlert],
        }));
      },

      removeAlert: (id) => {
        set((state) => ({
          priceAlerts: state.priceAlerts.filter((a) => a.id !== id),
        }));
      },

      triggerAlert: (id) => {
        set((state) => ({
          priceAlerts: state.priceAlerts.map((a) =>
            a.id === id ? { ...a, isTriggered: true, isActive: false } : a
          ),
        }));
      },

      toggleAlertModal: (open) => set({ isAlertModalOpen: open }),
    }),
    {
      name: 'oracle-x-storage',
      partialize: (state) => ({
        priceAlerts: state.priceAlerts,
        chartSymbol: state.chartSymbol,
        recentSymbols: state.recentSymbols,
      }),
      // v1 dropped `settings` (a theme and a language picker that nothing in the
      // app ever read). Removing it from `partialize` only stops it being
      // written: `persist` shallow-merges whatever is already in localStorage
      // over the initial state, so every existing browser would keep merging a
      // dead `settings` key back into the store forever — invisible to
      // TypeScript and confusing to whoever greps for it next.
      //
      // Envelopes written before this have no `version` field, which `persist`
      // reads as 0, so the migration runs exactly once per browser.
      version: 1,
      migrate: (persisted, version) => {
        if (version === 0 && persisted && typeof persisted === 'object') {
          const { settings: _dropped, ...rest } = persisted as Record<string, unknown>;
          return rest;
        }
        return persisted;
      },
    }
  )
);
