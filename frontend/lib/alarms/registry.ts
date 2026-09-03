/**
 * What can be watched, and how each one is described to the user.
 *
 * Metadata only — no fetching, no React. The builder UI reads this to decide
 * which inputs to render, the engine reads `minIntervalMs` to decide how often
 * a source may be polled, and `describe.ts` reads the labels and units to write
 * the preview sentence. Adding a thirteenth surface means adding one record
 * here plus one fetcher in `sources.ts`; nothing else changes.
 *
 * Icons are named rather than imported so this module stays free of React and
 * runs under the node-environment vitest suite. `components/alarms/icons.ts`
 * resolves the names.
 */

import { DEFAULT_COOLDOWN_MS, type AlarmCondition, type AlarmSourceId } from './types';

export type AlarmGroupId = 'market' | 'derivatives' | 'signals' | 'news';

export const ALARM_GROUPS: { id: AlarmGroupId; label: string }[] = [
  { id: 'market', label: 'Market' },
  { id: 'derivatives', label: 'Derivatives' },
  { id: 'signals', label: 'Macro & Signals' },
  { id: 'news', label: 'News & Events' },
];

export type AlarmIconName =
  | 'trending'
  | 'percent'
  | 'coins'
  | 'flame'
  | 'pizza'
  | 'radar'
  | 'gauge'
  | 'crown'
  | 'newspaper'
  | 'calendar'
  | 'link'
  | 'scale';

export interface AlarmField {
  key: string;
  label: string;
  /** Rendered after the input and in the preview sentence. Empty for unitless. */
  unit: string;
  decimals: number;
  /** Prefix rather than suffix — currencies read `$70.000`, not `70.000$`. */
  prefix?: string;
}

export interface AlarmStateOption {
  value: string;
  label: string;
}

export interface AlarmParamSpec {
  key: string;
  label: string;
  kind: 'symbol' | 'text' | 'select';
  placeholder?: string;
  options?: AlarmStateOption[];
  required: boolean;
  hint?: string;
}

export interface AlarmSourceMeta {
  id: AlarmSourceId;
  label: string;
  group: AlarmGroupId;
  icon: AlarmIconName;
  /** One line under the title in the builder — what this alarm actually watches. */
  description: string;
  params: AlarmParamSpec[];
  thresholdFields: AlarmField[];
  stateField?: { key: string; label: string; options: AlarmStateOption[] };
  supportsKeyword?: boolean;
  supportsCountdown?: boolean;
  /**
   * Floor between two fetches of this source, honoured by the engine.
   * Matched to how fast the upstream itself moves — polling the Pizza Index
   * every fifteen seconds would scrape a page that changes hourly.
   */
  minIntervalMs: number;
  /**
   * Starting cooldown for a repeating alarm.
   *
   * Event-shaped sources get a short one: during a liquidation cascade the
   * dedupe ring stops the *same* fill re-firing, but only the cooldown stops
   * thirty distinct fills becoming thirty notifications. A level source has no
   * such burst, and its hysteresis latch already does most of the work, so it
   * gets the long default.
   */
  defaultCooldownMs: number;
  defaultCondition: AlarmCondition;
}

const SECOND = 1000;
const MINUTE = 60 * SECOND;

export const ALARM_SOURCES: AlarmSourceMeta[] = [
  {
    id: 'price',
    label: 'Price',
    group: 'market',
    icon: 'trending',
    description:
      'The live price of one symbol. Crypto and equities; a symbol carries its own venue.',
    params: [
      {
        key: 'symbol',
        label: 'Symbol',
        kind: 'symbol',
        placeholder: 'BTCUSDT / NASDAQ:AAPL',
        required: true,
        hint: 'Crypto is BTCUSDT or BINANCE:ETHUSDT; an equity is the plain ticker.',
      },
    ],
    thresholdFields: [{ key: 'price', label: 'Price', unit: '', decimals: 2, prefix: '$' }],
    minIntervalMs: 15 * SECOND,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'threshold', field: 'price', op: 'above', value: 0 },
  },
  {
    id: 'change24h',
    label: '24h Change',
    group: 'market',
    icon: 'percent',
    description: 'How far one symbol has moved over the last 24 hours, in percent.',
    params: [
      { key: 'symbol', label: 'Symbol', kind: 'symbol', placeholder: 'BTC', required: true },
    ],
    thresholdFields: [{ key: 'change_24h', label: '24h Change', unit: '%', decimals: 2 }],
    minIntervalMs: MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'threshold', field: 'change_24h', op: 'below', value: -5 },
  },
  {
    id: 'btcDominance',
    label: 'BTC Dominance',
    group: 'market',
    icon: 'crown',
    description: "Bitcoin's share of the total crypto market capitalisation.",
    params: [],
    thresholdFields: [{ key: 'btc_dominance', label: 'Dominance', unit: '%', decimals: 2 }],
    minIntervalMs: MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'threshold', field: 'btc_dominance', op: 'above', value: 60 },
  },
  {
    id: 'funding',
    label: 'Funding Rate',
    group: 'derivatives',
    icon: 'scale',
    description: 'Perpetual funding rate. The backend’s own extreme flag can be watched instead.',
    params: [
      {
        key: 'symbol',
        label: 'Symbol',
        kind: 'symbol',
        placeholder: 'Empty = any',
        required: false,
      },
    ],
    thresholdFields: [{ key: 'rate', label: 'Rate', unit: '%', decimals: 4 }],
    stateField: {
      key: 'is_extreme',
      label: 'Server flag',
      options: [{ value: 'true', label: 'Extreme' }],
    },
    minIntervalMs: MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'threshold', field: 'rate', op: 'above', value: 0.05 },
  },
  {
    id: 'liquidation',
    label: 'Liquidation',
    group: 'derivatives',
    icon: 'flame',
    description: 'The USD size of a single liquidation. Every fill is its own event.',
    params: [
      {
        key: 'symbol',
        label: 'Symbol',
        kind: 'symbol',
        placeholder: 'Empty = any',
        required: false,
      },
      {
        key: 'side',
        label: 'Side',
        kind: 'select',
        required: false,
        options: [
          { value: '', label: 'Both' },
          { value: 'Long', label: 'Long' },
          { value: 'Short', label: 'Short' },
        ],
      },
    ],
    thresholdFields: [{ key: 'amount_usd', label: 'Size', unit: '', decimals: 0, prefix: '$' }],
    minIntervalMs: 30 * SECOND,
    defaultCooldownMs: MINUTE,
    defaultCondition: { kind: 'threshold', field: 'amount_usd', op: 'above', value: 1_000_000 },
  },
  {
    id: 'pizza',
    label: 'Pentagon Pizza Index',
    group: 'signals',
    icon: 'pizza',
    description: 'How busy the pizzerias around the Pentagon are against their own normal.',
    params: [],
    thresholdFields: [{ key: 'index', label: 'Index', unit: '×', decimals: 2 }],
    stateField: {
      key: 'status',
      label: 'Status',
      options: [
        { value: 'quiet', label: 'Quiet' },
        { value: 'normal', label: 'Normal' },
        { value: 'elevated', label: 'Elevated' },
        { value: 'spike', label: 'Spike' },
      ],
    },
    minIntervalMs: 10 * MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'state', field: 'status', states: ['elevated', 'spike'] },
  },
  {
    id: 'neh',
    label: 'NEH Index',
    group: 'signals',
    icon: 'radar',
    description: 'The highest probability across the prediction markets being watched.',
    params: [],
    thresholdFields: [{ key: 'index', label: 'Index', unit: '%', decimals: 1 }],
    stateField: {
      key: 'status',
      label: 'Status',
      options: [
        { value: 'calm', label: 'Calm' },
        { value: 'watch', label: 'Watch' },
        { value: 'happening', label: 'Happening' },
        { value: 'happened', label: 'Happened' },
      ],
    },
    minIntervalMs: 2 * MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'state', field: 'status', states: ['happening', 'happened'] },
  },
  {
    id: 'feargreed',
    label: 'Fear & Greed',
    group: 'signals',
    icon: 'gauge',
    description: 'The crypto fear & greed index (0-100).',
    params: [],
    thresholdFields: [{ key: 'value', label: 'Value', unit: '', decimals: 0 }],
    minIntervalMs: 5 * MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'threshold', field: 'value', op: 'below', value: 20 },
  },
  {
    id: 'chainAnomaly',
    label: 'Chain Anomaly',
    group: 'signals',
    icon: 'link',
    description: 'An irregularity the backend found on a chain. Every anomaly is its own event.',
    params: [
      {
        key: 'chain',
        label: 'Chain',
        kind: 'text',
        placeholder: 'Empty = all',
        required: false,
        hint: 'The chain key, e.g. bitcoin, ethereum, solana.',
      },
    ],
    thresholdFields: [{ key: 'magnitude', label: 'Magnitude', unit: '×', decimals: 2 }],
    stateField: {
      key: 'severity',
      label: 'Severity',
      options: [
        { value: 'high', label: 'High' },
        { value: 'notable', label: 'Notable' },
      ],
    },
    minIntervalMs: MINUTE,
    defaultCooldownMs: 5 * MINUTE,
    defaultCondition: { kind: 'state', field: 'severity', states: ['high'] },
  },
  {
    id: 'news',
    label: 'News',
    group: 'news',
    icon: 'newspaper',
    description: 'A keyword match in a headline or its summary.',
    params: [
      {
        key: 'assetType',
        label: 'Type',
        kind: 'select',
        required: false,
        options: [
          { value: '', label: 'All' },
          { value: 'crypto', label: 'Crypto' },
          { value: 'stock', label: 'Equities' },
        ],
      },
      {
        key: 'symbol',
        label: 'Symbol',
        kind: 'symbol',
        placeholder: 'Empty = all',
        required: false,
      },
    ],
    thresholdFields: [],
    supportsKeyword: true,
    minIntervalMs: 30 * SECOND,
    defaultCooldownMs: MINUTE,
    defaultCondition: { kind: 'keyword', terms: [], matchIn: 'both' },
  },
  {
    id: 'macroEvent',
    label: 'Macro Event',
    group: 'news',
    icon: 'calendar',
    description: 'Fires once a calendar event is within the lead time you set.',
    params: [
      {
        key: 'impact',
        label: 'Impact',
        kind: 'select',
        required: false,
        options: [
          { value: '', label: 'All' },
          { value: 'high', label: 'High' },
          { value: 'medium', label: 'Medium' },
          { value: 'low', label: 'Low' },
        ],
      },
    ],
    thresholdFields: [],
    supportsCountdown: true,
    minIntervalMs: MINUTE,
    defaultCooldownMs: 5 * MINUTE,
    defaultCondition: { kind: 'countdown', leadMinutes: 15 },
  },
  {
    id: 'polymarket',
    label: 'Polymarket',
    group: 'news',
    icon: 'coins',
    description: 'The probability of the leading outcome in one prediction market.',
    params: [
      {
        key: 'slug',
        label: 'Market slug',
        kind: 'text',
        placeholder: 'will-x-happen-by-2026',
        required: true,
        hint: 'The trailing part of the URL on the Polymarket page.',
      },
    ],
    thresholdFields: [
      { key: 'leading_price', label: 'Leading probability', unit: '%', decimals: 1 },
      { key: 'drift_24h', label: '24h drift', unit: 'pts', decimals: 1 },
    ],
    minIntervalMs: 2 * MINUTE,
    defaultCooldownMs: DEFAULT_COOLDOWN_MS,
    defaultCondition: { kind: 'threshold', field: 'leading_price', op: 'above', value: 80 },
  },
];

const BY_ID = new Map(ALARM_SOURCES.map((source) => [source.id, source]));

export function getAlarmSource(id: AlarmSourceId): AlarmSourceMeta {
  const source = BY_ID.get(id);
  // A persisted alarm naming a source that no longer exists is a bug in the
  // store migration, not something to paper over with a placeholder.
  if (!source) throw new Error(`Unknown alarm source: ${id}`);
  return source;
}

export function findAlarmField(id: AlarmSourceId, fieldKey: string): AlarmField | undefined {
  return getAlarmSource(id).thresholdFields.find((field) => field.key === fieldKey);
}
