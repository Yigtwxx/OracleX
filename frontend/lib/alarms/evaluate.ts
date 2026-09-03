/**
 * The alarm decision function — the one place that says "fire" or "stay quiet".
 *
 * Pure on purpose. `vitest.config.ts` only collects `lib/**` in a node
 * environment, and this is the logic worth pinning: every guard below exists
 * because breaking it produces a *silent* fault — an alarm that fires on a gap,
 * or one that never fires at all. Neither surfaces as an error in the UI.
 *
 * The engine hook owns scheduling and I/O and makes no decisions of its own.
 */

import {
  type Alarm,
  type AlarmCondition,
  type Reading,
  type ThresholdOp,
  HYSTERESIS_FRACTION,
  NO_READING_STATUSES,
  SEEN_KEYS_LIMIT,
} from './types';

/** The fields a decision asks the caller to write back onto the alarm. */
export interface AlarmPatch {
  lastTriggeredAt?: string;
  triggerCount?: number;
  armed?: boolean;
  seenKeys?: string[];
}

export type AlarmDecision =
  /** Notify, then apply `patch`. `detail` is the observed value, for the body. */
  | { action: 'trigger'; patch: AlarmPatch; detail: string }
  /** No notification, but the hysteresis latch has cleared — persist `patch`. */
  | { action: 'rearm'; patch: AlarmPatch }
  | { action: 'none' };

const NONE: AlarmDecision = { action: 'none' };

/**
 * What a condition made of one reading.
 *
 * `latchable` marks a level that can sit on the wrong side of the threshold for
 * many polls; those get the hysteresis latch. A keyword hit cannot, so it does
 * not.
 */
interface Match {
  met: boolean;
  latchable: boolean;
  /** Level has retreated far enough to re-arm. Only read when `latchable`. */
  rearm: boolean;
}

/**
 * A reading is a number only when it actually is one.
 *
 * `null` means the upstream had nothing to say, and this codebase is consistent
 * about that (`lib/api.ts` header comment, `home_service.py:_unknown_onchain`).
 * Coercing it would make `value <= threshold` true for every "below" alarm the
 * moment a source went dark — a spurious notification indistinguishable from a
 * real one.
 */
function numeric(value: number | string | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function thresholdMet(current: number, op: ThresholdOp, target: number): boolean {
  return op === 'above' ? current >= target : current <= target;
}

/**
 * Has the reading retreated far enough past the threshold to re-arm?
 *
 * The band is a fraction of the threshold rather than a fixed number because
 * one alarm type spans a 0.0001 funding rate and a 100,000 BTC price.
 */
function retreated(current: number, op: ThresholdOp, target: number): boolean {
  const band = Math.abs(target) * HYSTERESIS_FRACTION;
  return op === 'above' ? current < target - band : current > target + band;
}

function pushSeen(seenKeys: string[], key: string): string[] {
  return [...seenKeys, key].slice(-SEEN_KEYS_LIMIT);
}

/** `null` when the field this condition needs has no reading at all. */
function match(condition: AlarmCondition, reading: Reading): Match | null {
  switch (condition.kind) {
    case 'threshold': {
      const current = numeric(reading.values[condition.field]);
      if (current === null) return null;
      return {
        met: thresholdMet(current, condition.op, condition.value),
        latchable: true,
        rearm: retreated(current, condition.op, condition.value),
      };
    }

    case 'state': {
      const current = reading.values[condition.field];
      if (current === null || current === undefined) return null;
      const inSet = condition.states.includes(String(current));
      return { met: inSet, latchable: true, rearm: !inSet };
    }

    case 'keyword': {
      const haystack = [
        condition.matchIn === 'summary' ? '' : String(reading.values.title ?? ''),
        condition.matchIn === 'title' ? '' : String(reading.values.summary ?? ''),
      ]
        .join(' ')
        .toLocaleLowerCase('tr');

      const hit = condition.terms.some((term) => {
        const needle = term.trim().toLocaleLowerCase('tr');
        return needle.length > 0 && haystack.includes(needle);
      });
      return { met: hit, latchable: false, rearm: false };
    }

    case 'countdown': {
      const minutesUntil = numeric(reading.values.minutesUntil);
      if (minutesUntil === null) return null;
      // Already under way is not "about to start": a countdown that fired on
      // negative values would announce every past event on the first tick.
      const met = minutesUntil >= 0 && minutesUntil <= condition.leadMinutes;
      return { met, latchable: false, rearm: false };
    }
  }
}

/**
 * Decide what one alarm should do about one reading.
 *
 * `now` is injected rather than read from the clock so cooldown behaviour is
 * testable without waiting fifteen minutes.
 */
export function evaluateAlarm(alarm: Alarm, reading: Reading, now: number): AlarmDecision {
  if (!alarm.enabled) return NONE;

  // A cached replay is not a new observation. Every board payload here carries
  // `stale`, and without this an outage would re-fire every alarm on the same
  // frozen numbers for as long as it lasted.
  if (reading.stale) return NONE;

  // The macro endpoints never answer 503; they say "no reading" in-band. Branch
  // on status, not on HTTP failure — see `hasReading` in lib/pizza-index.ts.
  if (reading.status && (NO_READING_STATUSES as readonly string[]).includes(reading.status)) {
    return NONE;
  }

  const eventShaped = reading.eventShaped === true;
  if (eventShaped && alarm.seenKeys.includes(reading.key)) return NONE;

  const outcome = match(alarm.condition, reading);
  if (outcome === null) return NONE;

  // The latch only makes sense for a level. An event-shaped reading is deduped
  // by key instead, above.
  const latched = !eventShaped && outcome.latchable;
  if (latched && !alarm.armed) {
    return outcome.rearm ? { action: 'rearm', patch: { armed: true } } : NONE;
  }

  if (!outcome.met) return NONE;
  if (alarm.repeat === 'once' && alarm.triggerCount > 0) return NONE;
  if (
    alarm.repeat === 'always' &&
    alarm.lastTriggeredAt !== undefined &&
    now - Date.parse(alarm.lastTriggeredAt) < alarm.cooldownMs
  ) {
    return NONE;
  }

  const patch: AlarmPatch = {
    lastTriggeredAt: new Date(now).toISOString(),
    triggerCount: alarm.triggerCount + 1,
  };
  if (latched) patch.armed = false;
  if (eventShaped) patch.seenKeys = pushSeen(alarm.seenKeys, reading.key);

  return { action: 'trigger', patch, detail: reading.display };
}
