/**
 * The alarm domain model.
 *
 * One shape covers every surface a user can watch, because the previous model
 * — `{ symbol, targetPrice, condition }` — could not describe a Pizza Index
 * status, a news keyword or a countdown to a macro event without growing a
 * nullable field per source. A discriminated `condition` keeps the evaluator
 * exhaustive: adding a condition kind breaks the switch until it is handled.
 */

export type AlarmSourceId =
  | 'price'
  | 'change24h'
  | 'funding'
  | 'liquidation'
  | 'pizza'
  | 'neh'
  | 'feargreed'
  | 'btcDominance'
  | 'news'
  | 'macroEvent'
  | 'chainAnomaly'
  | 'polymarket';

export type ThresholdOp = 'above' | 'below';

export type AlarmCondition =
  | { kind: 'threshold'; field: string; op: ThresholdOp; value: number }
  /** Server-computed classification — Pizza `spike`, anomaly `high`. Never re-derived here. */
  | { kind: 'state'; field: string; states: string[] }
  | { kind: 'keyword'; terms: string[]; matchIn: 'title' | 'summary' | 'both' }
  /** Fires once an event is within `leadMinutes` of starting. */
  | { kind: 'countdown'; leadMinutes: number };

export type AlarmRepeat = 'once' | 'always';

export interface Alarm {
  id: string;
  sourceId: AlarmSourceId;
  /** Source-specific selectors: `{ symbol }`, `{ slug }`, `{ side }`, `{ impact }`. */
  params: Record<string, string>;
  condition: AlarmCondition;
  repeat: AlarmRepeat;
  /** Only consulted when `repeat === 'always'`. */
  cooldownMs: number;
  enabled: boolean;
  createdAt: string;
  lastTriggeredAt: string | undefined;
  triggerCount: number;
  /**
   * Dedupe keys for event-shaped sources (news, liquidations, anomalies), where
   * the same item reappears in every poll. A bounded ring — the newest
   * `SEEN_KEYS_LIMIT` entries — because an unbounded one would grow forever in
   * localStorage for a keyword alarm on a busy feed.
   */
  seenKeys: string[];
  /**
   * Hysteresis latch for threshold alarms. Cleared on a trigger and only reset
   * once the reading retreats past the threshold by `HYSTERESIS_FRACTION`, so a
   * value oscillating on the boundary produces one notification rather than one
   * per tick.
   */
  armed: boolean;
}

/**
 * One observation handed to the evaluator.
 *
 * `values` is deliberately `number | string | null` rather than `number`: a
 * missing reading arrives as `null` throughout this codebase and must never be
 * coerced to `0`, which is itself a real reading for a funding rate or a
 * stablecoin's daily change.
 */
export interface Reading {
  /** Stable identity for event-shaped sources; the source id for scalar ones. */
  key: string;
  values: Record<string, number | string | null>;
  /** Replayed from cache after an upstream fault — must not re-trigger. */
  stale: boolean;
  /** `unavailable` / `insufficient_data` from the endpoints that never 503. */
  status?: string;
  /**
   * True when this reading is a discrete item — a headline, a liquidation, an
   * anomaly — rather than a level that persists between polls.
   *
   * It belongs to the reading and not to the condition kind: a liquidation
   * alarm is a *threshold* on `amount_usd` yet every fill is its own event, so
   * deduping by key is right and the hysteresis latch is meaningless. Deciding
   * this from `condition.kind` would silently latch such an alarm after the
   * first fill and never fire it again.
   */
  eventShaped?: boolean;
  /** Human-facing rendering of the observed value, for the notification body. */
  display: string;
}

export interface TriggerEvent {
  id: string;
  alarmId: string;
  sourceId: AlarmSourceId;
  title: string;
  body: string;
  firedAt: string;
}

/** Statuses that mean "no reading", not "a reading of zero". */
export const NO_READING_STATUSES = ['unavailable', 'insufficient_data'] as const;

export const SEEN_KEYS_LIMIT = 200;

/** Re-arm band, as a fraction of the threshold's magnitude. */
export const HYSTERESIS_FRACTION = 0.005;

export const DEFAULT_COOLDOWN_MS = 15 * 60 * 1000;

export const ALARM_HISTORY_LIMIT = 50;
