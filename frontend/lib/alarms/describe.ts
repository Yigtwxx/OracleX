/**
 * Alarm → one English sentence.
 *
 * The builder shows this before the alarm is saved and the list shows it after,
 * so a user never has to reconstruct what an alarm does from a row of operator
 * symbols. Kept pure and separate from the registry so it can be tested without
 * a DOM.
 */

import { findAlarmField, getAlarmSource, type AlarmField } from './registry';
import type { Alarm, AlarmSourceId, ThresholdOp } from './types';

const OP_PHRASE: Record<ThresholdOp, string> = {
  above: 'rises above',
  below: 'falls below',
};

const REPEAT_PHRASE = {
  once: 'notify once',
  always: 'notify every time',
} as const;

/**
 * Format a number the way its field is written elsewhere on the board.
 *
 * `en-US` grouping, because every other number in the app is rendered that way
 * (`lib/chain-format`, `components/home/LiquidationFeed`) and a preview sentence
 * mixing `70.000,00` with `0.05%` reads as two different applications.
 */
export function formatFieldValue(field: AlarmField | undefined, value: number): string {
  const decimals = field?.decimals ?? 2;
  const body = value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return `${field?.prefix ?? ''}${body}${field?.unit ? ` ${field.unit}`.trimEnd() : ''}`;
}

export function formatSourceValue(
  sourceId: AlarmSourceId,
  fieldKey: string,
  value: number
): string {
  return formatFieldValue(findAlarmField(sourceId, fieldKey), value);
}

/** "BTCUSDT · Price" — the subject an alarm is about. */
export function describeSubject(alarm: Alarm): string {
  const source = getAlarmSource(alarm.sourceId);
  const selector = alarm.params.symbol || alarm.params.slug || alarm.params.chain;
  return selector ? `${selector} · ${source.label}` : source.label;
}

function describeCondition(alarm: Alarm): string {
  const source = getAlarmSource(alarm.sourceId);

  switch (alarm.condition.kind) {
    case 'threshold': {
      const field = findAlarmField(alarm.sourceId, alarm.condition.field);
      const amount = formatFieldValue(field, alarm.condition.value);
      const noun = (field?.label ?? alarm.condition.field).toLowerCase();
      return `${noun} ${OP_PHRASE[alarm.condition.op]} ${amount}`;
    }

    case 'state': {
      const options = source.stateField?.options ?? [];
      const labels = alarm.condition.states.map(
        (state) => options.find((option) => option.value === state)?.label ?? state
      );
      const noun = (source.stateField?.label ?? 'status').toLowerCase();
      return `${noun} turns ${labels.join(' or ')}`;
    }

    case 'keyword': {
      const terms = alarm.condition.terms.filter((term) => term.trim().length > 0);
      const where =
        alarm.condition.matchIn === 'title'
          ? 'the title'
          : alarm.condition.matchIn === 'summary'
            ? 'the summary'
            : 'the title or summary';
      // An unsaved draft reaches here with no terms; say so rather than
      // rendering "appears in …" and implying it would match everything.
      if (terms.length === 0) return `no keyword set for ${where}`;
      return `${terms.map((term) => `“${term.trim()}”`).join(' or ')} appears in ${where}`;
    }

    case 'countdown':
      return `${alarm.condition.leadMinutes} minutes before it starts`;
  }
}

function describeFilters(alarm: Alarm): string {
  const source = getAlarmSource(alarm.sourceId);
  const parts = source.params
    .filter((spec) => spec.kind === 'select' && alarm.params[spec.key])
    .map((spec) => {
      const value = alarm.params[spec.key];
      const label = spec.options?.find((option) => option.value === value)?.label ?? value;
      return `${spec.label.toLowerCase()}: ${label}`;
    });
  return parts.length > 0 ? ` (${parts.join(', ')})` : '';
}

/**
 * The full sentence, e.g.
 * "BTCUSDT · Price — price rises above $70,000.00, notify once."
 */
export function describeAlarm(alarm: Alarm): string {
  return `${describeSubject(alarm)} — ${describeCondition(alarm)}${describeFilters(alarm)}, ${
    REPEAT_PHRASE[alarm.repeat]
  }.`;
}

/** Short form for a notification title, without the repeat clause. */
export function describeAlarmShort(alarm: Alarm): string {
  return `${describeSubject(alarm)} — ${describeCondition(alarm)}`;
}

// ── Mail prose ──────────────────────────────────────────────────────────────
//
// The alarm mail is written as a short article rather than a dashboard: a
// sentence that carries the whole message, then a supporting line, then the
// figures. Both sentences are composed here rather than in the Jinja template
// that renders them, because this module is already the one place that knows
// how to turn a condition into English — and the alternative is a second
// implementation of the same grammar, in Python, that drifts from this one.

const HEADLINE_VERB: Record<ThresholdOp, string> = {
  above: 'rose above',
  below: 'fell below',
};

/**
 * The sentence the message leads with.
 *
 * Deliberately says "your level" for a threshold: the reader wrote this rule,
 * and naming it as theirs is what separates an alarm from a market update they
 * did not ask for.
 */
export function describeMailHeadline(alarm: Alarm): string {
  const subject = describeSubject(alarm);
  const source = getAlarmSource(alarm.sourceId);

  switch (alarm.condition.kind) {
    case 'threshold': {
      const field = findAlarmField(alarm.sourceId, alarm.condition.field);
      const amount = formatFieldValue(field, alarm.condition.value);
      return `${subject} ${HEADLINE_VERB[alarm.condition.op]} your ${amount} level.`;
    }

    case 'state': {
      const options = source.stateField?.options ?? [];
      const labels = alarm.condition.states.map(
        (state) => options.find((option) => option.value === state)?.label ?? state
      );
      return `${subject} turned ${labels.join(' or ')}.`;
    }

    case 'keyword': {
      const terms = alarm.condition.terms.filter((term) => term.trim().length > 0);
      const quoted = terms.map((term) => `“${term.trim()}”`).join(' or ');
      return terms.length > 0
        ? `${quoted} just appeared in the news.`
        : `${subject} matched a headline.`;
    }

    case 'countdown':
      return `${subject} starts in ${alarm.condition.leadMinutes} minutes.`;
  }
}

/**
 * The supporting line under the headline.
 *
 * Built from whichever parts exist rather than from a fixed template: a first
 * fire has no count worth mentioning, a one-shot alarm has no cooldown to
 * explain, and a state change has no distance. Each clause earns its place or
 * is left out — padding this to a fixed length would be the surest way to make
 * it stop being read.
 */
export function describeMailLead(alarm: Alarm, observed: string, distance?: string): string {
  const parts: string[] = [`The latest reading is ${observed}.`];

  if (distance) {
    parts.push(`That is ${distance} past the level you set.`);
  }

  if (alarm.triggerCount > 0) {
    const times = alarm.triggerCount + 1;
    parts.push(`This alarm has now fired ${times} times.`);
  }

  if (alarm.repeat === 'once') {
    parts.push('It was set to notify once, so it will not fire again.');
  } else {
    const minutes = Math.round(alarm.cooldownMs / 60000);
    parts.push(`It keeps watching, with a ${minutes}-minute pause between notifications.`);
  }

  return parts.join(' ');
}

/**
 * How far the reading is past the threshold, as a signed percentage.
 *
 * `undefined` rather than `"0%"` whenever it cannot be computed honestly: a
 * non-threshold condition has no level, a missing reading has no value, and a
 * threshold of zero — a real setting for a funding rate — has no denominator.
 * A fabricated figure in this position is worse than a missing column.
 */
export function distanceFromThreshold(
  alarm: Alarm,
  value: number | string | null
): string | undefined {
  if (alarm.condition.kind !== 'threshold') return undefined;
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;

  const threshold = alarm.condition.value;
  if (threshold === 0) return undefined;

  const percent = ((value - threshold) / Math.abs(threshold)) * 100;
  const sign = percent >= 0 ? '+' : '−';
  return `${sign}${Math.abs(percent).toFixed(2)}%`;
}

/** The threshold itself, formatted the way the rest of the alarm renders it. */
export function thresholdDisplay(alarm: Alarm): string | undefined {
  if (alarm.condition.kind !== 'threshold') return undefined;
  return formatFieldValue(
    findAlarmField(alarm.sourceId, alarm.condition.field),
    alarm.condition.value
  );
}
