import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import {
  ALARM_HISTORY_LIMIT,
  DEFAULT_COOLDOWN_MS,
  type Alarm,
  type AlarmSourceId,
  type TriggerEvent,
} from '@/lib/alarms/types';
// `import type`: `lib/alarms/email` imports `lib/api`, which imports this file.
// A value import would close that cycle at runtime; a type import is erased.
import type { AlarmEmailIdentity } from '@/lib/alarms/email';

/** What the builder hands `addAlarm`; the store owns the rest of the record. */
export type NewAlarm = Omit<
  Alarm,
  'id' | 'createdAt' | 'lastTriggeredAt' | 'triggerCount' | 'seenKeys' | 'armed'
>;

/** Opening the modal already pointed at a source, e.g. from a chart. */
export interface AlarmDraft {
  sourceId: AlarmSourceId;
  params: Record<string, string>;
}

function newAlarmId(): string {
  // `crypto.randomUUID` is unavailable over plain HTTP on some hosts; the
  // fallback only has to be unique within one browser's localStorage.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `alarm_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

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

  // Alarm state. The alarms themselves and the log of what has fired are
  // persisted; the modal's open/draft state deliberately is not.
  alarms: Alarm[];
  alarmHistory: TriggerEvent[];
  isAlarmModalOpen: boolean;
  /** Pre-selected source for a modal opened from somewhere with context. */
  alarmDraft: AlarmDraft | undefined;
  /**
   * The confirmed mail address alarms are sent to, and the token proving it was
   * confirmed. Persisted alongside the alarms, because it is the same kind of
   * thing: a preference this browser holds, not an account property.
   *
   * `undefined` covers both "never set" and "removed". There is no separate
   * enabled flag — an address that exists is an address that receives, and a
   * user who wants to stop deletes it. A flag would add a state where mail is
   * configured, silent, and looks broken.
   */
  alarmEmail: AlarmEmailIdentity | undefined;

  // Actions
  setNewsItems: (items: NewsItem[]) => void;
  selectNews: (news: NewsItem) => void;
  setChartSymbol: (symbol: string) => void;
  setAnalysisJobId: (newsId: string, jobId: string) => void;
  setLoadingNews: (loading: boolean) => void;
  setCurrentPrice: (price: number) => void;
  clearSelection: () => void;

  // Alarm Actions
  addAlarm: (alarm: NewAlarm) => void;
  updateAlarm: (id: string, patch: Partial<Alarm>) => void;
  removeAlarm: (id: string) => void;
  toggleAlarmEnabled: (id: string) => void;
  /** Applies the evaluator's patch and appends to the history in one write. */
  recordAlarmTrigger: (id: string, patch: Partial<Alarm>, event: TriggerEvent) => void;
  clearAlarmHistory: () => void;
  openAlarmModal: (draft?: AlarmDraft) => void;
  closeAlarmModal: () => void;
  /** Pass `undefined` to stop mailing this browser's alarms. */
  setAlarmEmail: (identity: AlarmEmailIdentity | undefined) => void;
}

/**
 * v1 price alerts, as the general alarm model.
 *
 * A triggered one-shot alert arrives with `isActive: false`; it is carried over
 * disabled rather than dropped, so a user who reopens the modal recognises what
 * they had set rather than finding it empty.
 */
function migratePriceAlerts(raw: unknown): Alarm[] {
  if (!Array.isArray(raw)) return [];

  return raw.flatMap((entry): Alarm[] => {
    if (!entry || typeof entry !== 'object') return [];
    const legacy = entry as {
      id?: unknown;
      symbol?: unknown;
      targetPrice?: unknown;
      condition?: unknown;
      isActive?: unknown;
      isTriggered?: unknown;
      createdAt?: unknown;
    };

    const symbol = typeof legacy.symbol === 'string' ? legacy.symbol : '';
    const target = typeof legacy.targetPrice === 'number' ? legacy.targetPrice : Number.NaN;
    const op = legacy.condition === 'below' ? 'below' : 'above';
    // A row missing its symbol or price cannot be evaluated, and inventing a
    // value for it would produce an alarm that fires on nothing.
    if (!symbol || !Number.isFinite(target)) return [];

    return [
      {
        id: typeof legacy.id === 'string' ? legacy.id : newAlarmId(),
        sourceId: 'price',
        params: { symbol },
        condition: { kind: 'threshold', field: 'price', op, value: target },
        repeat: 'once',
        cooldownMs: DEFAULT_COOLDOWN_MS,
        enabled: legacy.isActive === true && legacy.isTriggered !== true,
        createdAt:
          typeof legacy.createdAt === 'string' ? legacy.createdAt : new Date().toISOString(),
        lastTriggeredAt: undefined,
        triggerCount: legacy.isTriggered === true ? 1 : 0,
        seenKeys: [],
        armed: true,
      },
    ];
  });
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
      alarms: [],
      alarmHistory: [],
      isAlarmModalOpen: false,
      alarmDraft: undefined,
      alarmEmail: undefined,

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

      // Alarm Actions
      addAlarm: (draft) => {
        const alarm: Alarm = {
          ...draft,
          // randomUUID rather than a timestamp: two alarms created in the same
          // millisecond used to share an id, and the second delete removed both.
          id: newAlarmId(),
          createdAt: new Date().toISOString(),
          lastTriggeredAt: undefined,
          triggerCount: 0,
          seenKeys: [],
          armed: true,
        };
        set((state) => ({ alarms: [...state.alarms, alarm] }));
      },

      updateAlarm: (id, patch) =>
        set((state) => ({
          alarms: state.alarms.map((alarm) => (alarm.id === id ? { ...alarm, ...patch } : alarm)),
        })),

      removeAlarm: (id) =>
        set((state) => ({ alarms: state.alarms.filter((alarm) => alarm.id !== id) })),

      toggleAlarmEnabled: (id) =>
        set((state) => ({
          alarms: state.alarms.map((alarm) =>
            alarm.id === id
              ? {
                  // Re-enabling re-arms: an alarm switched back on is a fresh
                  // intent, not a resumption of the latch it was left in.
                  ...alarm,
                  enabled: !alarm.enabled,
                  armed: alarm.enabled ? alarm.armed : true,
                }
              : alarm
          ),
        })),

      recordAlarmTrigger: (id, patch, event) =>
        set((state) => ({
          alarms: state.alarms.map((alarm) => (alarm.id === id ? { ...alarm, ...patch } : alarm)),
          alarmHistory: [event, ...state.alarmHistory].slice(0, ALARM_HISTORY_LIMIT),
        })),

      clearAlarmHistory: () => set({ alarmHistory: [] }),

      openAlarmModal: (draft) => set({ isAlarmModalOpen: true, alarmDraft: draft }),

      closeAlarmModal: () => set({ isAlarmModalOpen: false, alarmDraft: undefined }),

      setAlarmEmail: (identity) => set({ alarmEmail: identity }),
    }),
    {
      name: 'oracle-x-storage',
      partialize: (state) => ({
        alarms: state.alarms,
        alarmHistory: state.alarmHistory,
        alarmEmail: state.alarmEmail,
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
      // reads as 0, so each migration runs exactly once per browser.
      //
      // v2 replaces the price-only `priceAlerts` with the general `alarms`. It
      // must delete the old key for the same shallow-merge reason as `settings`
      // above, not merely stop writing it.
      version: 2,
      migrate: (persisted, version) => {
        if (!persisted || typeof persisted !== 'object') return persisted;
        let state = persisted as Record<string, unknown>;

        if (version < 1) {
          const { settings: _dropped, ...rest } = state;
          state = rest;
        }

        if (version < 2) {
          const { priceAlerts, ...rest } = state;
          state = { ...rest, alarms: migratePriceAlerts(priceAlerts) };
        }

        return state;
      },
    }
  )
);
