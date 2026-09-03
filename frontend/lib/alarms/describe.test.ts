import { describe, expect, it } from 'vitest';
import {
  describeAlarm,
  describeMailHeadline,
  describeMailLead,
  describeSubject,
  distanceFromThreshold,
  formatSourceValue,
} from './describe';
import { ALARM_SOURCES, getAlarmSource } from './registry';
import { DEFAULT_COOLDOWN_MS, type Alarm } from './types';

function alarm(overrides: Partial<Alarm> = {}): Alarm {
  return {
    id: 'a1',
    sourceId: 'price',
    params: { symbol: 'BTCUSDT' },
    condition: { kind: 'threshold', field: 'price', op: 'above', value: 70000 },
    repeat: 'once',
    cooldownMs: DEFAULT_COOLDOWN_MS,
    enabled: true,
    createdAt: '2026-08-24T11:00:00.000Z',
    lastTriggeredAt: undefined,
    triggerCount: 0,
    seenKeys: [],
    armed: true,
    ...overrides,
  };
}

describe('describeAlarm', () => {
  it('writes a threshold alarm as a sentence', () => {
    expect(describeAlarm(alarm())).toBe(
      'BTCUSDT · Price — price rises above $70,000.00, notify once.'
    );
  });

  it('distinguishes the two operators', () => {
    const below = alarm({
      condition: { kind: 'threshold', field: 'price', op: 'below', value: 50000 },
    });
    expect(describeAlarm(below)).toContain('falls below');
  });

  it('names the repeat mode', () => {
    expect(describeAlarm(alarm({ repeat: 'always' }))).toContain('notify every time');
  });

  it('renders a state condition with the labels the picker showed', () => {
    const pizza = alarm({
      sourceId: 'pizza',
      params: {},
      condition: { kind: 'state', field: 'status', states: ['elevated', 'spike'] },
    });
    expect(describeAlarm(pizza)).toBe(
      'Pentagon Pizza Index — status turns Elevated or Spike, notify once.'
    );
  });

  it('quotes keyword terms', () => {
    const news = alarm({
      sourceId: 'news',
      params: {},
      condition: { kind: 'keyword', terms: ['fed', 'cpi'], matchIn: 'title' },
    });
    expect(describeAlarm(news)).toContain('“fed” or “cpi” appears in the title');
  });

  it('says outright when a keyword draft has no terms yet', () => {
    // Rendering "appears in …" for an empty term list would preview an alarm
    // that matches everything.
    const draft = alarm({
      sourceId: 'news',
      params: {},
      condition: { kind: 'keyword', terms: [], matchIn: 'both' },
    });
    expect(describeAlarm(draft)).toContain('no keyword set');
  });

  it('renders a countdown in minutes', () => {
    const event = alarm({
      sourceId: 'macroEvent',
      params: {},
      condition: { kind: 'countdown', leadMinutes: 30 },
    });
    expect(describeAlarm(event)).toContain('30 minutes before it starts');
  });

  it('appends select filters so a scoped alarm does not read as a global one', () => {
    const liq = alarm({
      sourceId: 'liquidation',
      params: { side: 'Long' },
      condition: { kind: 'threshold', field: 'amount_usd', op: 'above', value: 1_000_000 },
    });
    expect(describeAlarm(liq)).toContain('(side: Long)');
  });
});

describe('describeSubject', () => {
  it('drops the selector for a source that has none', () => {
    expect(describeSubject(alarm({ sourceId: 'feargreed', params: {} }))).toBe('Fear & Greed');
  });
});

describe('formatSourceValue', () => {
  it('uses the field decimals and unit', () => {
    expect(formatSourceValue('funding', 'rate', 0.0612)).toBe('0.0612 %');
    expect(formatSourceValue('feargreed', 'value', 18)).toBe('18');
  });
});

describe('registry integrity', () => {
  it('every source default condition names a field the source declares', () => {
    for (const source of ALARM_SOURCES) {
      const condition = source.defaultCondition;
      if (condition.kind === 'threshold') {
        expect(source.thresholdFields.map((f) => f.key)).toContain(condition.field);
      }
      if (condition.kind === 'state') {
        expect(source.stateField?.key).toBe(condition.field);
        for (const state of condition.states) {
          expect(source.stateField?.options.map((o) => o.value)).toContain(state);
        }
      }
    }
  });

  it('every source can be described without throwing', () => {
    for (const source of ALARM_SOURCES) {
      const required = Object.fromEntries(
        source.params.filter((p) => p.required).map((p) => [p.key, 'X'])
      );
      expect(() =>
        describeAlarm(
          alarm({ sourceId: source.id, params: required, condition: source.defaultCondition })
        )
      ).not.toThrow();
    }
  });

  it('source ids are unique', () => {
    const ids = ALARM_SOURCES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('resolves each source by id', () => {
    for (const source of ALARM_SOURCES) {
      expect(getAlarmSource(source.id).label).toBe(source.label);
    }
  });
});

describe('mail prose', () => {
  it('names the level as the reader’s own in a threshold headline', () => {
    // "your $70,000.00 level" rather than "the threshold": the reader wrote
    // this rule, and that is what separates an alarm from a market update.
    expect(describeMailHeadline(alarm())).toBe('BTCUSDT · Price rose above your $70,000.00 level.');
  });

  it('flips the verb for a below condition', () => {
    const below = alarm({
      condition: { kind: 'threshold', field: 'price', op: 'below', value: 50000 },
    });
    expect(describeMailHeadline(below)).toContain('fell below');
  });

  it('writes a state headline from the labels the picker showed', () => {
    const pizza = alarm({
      sourceId: 'pizza',
      params: {},
      condition: { kind: 'state', field: 'status', states: ['spike'] },
    });
    expect(describeMailHeadline(pizza)).toBe('Pentagon Pizza Index turned Spike.');
  });

  it('leads a keyword headline with the term that matched', () => {
    const news = alarm({
      sourceId: 'news',
      params: {},
      condition: { kind: 'keyword', terms: ['fed'], matchIn: 'title' },
    });
    expect(describeMailHeadline(news)).toContain('“fed”');
  });

  it('every source produces a headline without throwing', () => {
    for (const source of ALARM_SOURCES) {
      const required = Object.fromEntries(
        source.params.filter((p) => p.required).map((p) => [p.key, 'X'])
      );
      expect(() =>
        describeMailHeadline(
          alarm({ sourceId: source.id, params: required, condition: source.defaultCondition })
        )
      ).not.toThrow();
    }
  });

  it('omits the count clause on a first fire', () => {
    // "has now fired 1 times" is both wrong and noise.
    const lead = describeMailLead(alarm({ triggerCount: 0 }), '$72,450.00');
    expect(lead).not.toContain('fired');
  });

  it('mentions the cooldown only for a repeating alarm', () => {
    expect(describeMailLead(alarm({ repeat: 'once' }), '$1')).toContain('will not fire again');
    expect(describeMailLead(alarm({ repeat: 'always' }), '$1')).toContain('minute pause');
  });

  it('states the distance when there is one', () => {
    expect(describeMailLead(alarm(), '$72,450.00', '+3.50%')).toContain('+3.50% past the level');
  });
});

describe('distanceFromThreshold', () => {
  it('measures how far past the level the reading sits', () => {
    expect(distanceFromThreshold(alarm(), 72450)).toBe('+3.50%');
  });

  it('signs a reading that has not cleared the level', () => {
    expect(distanceFromThreshold(alarm(), 69300)).toBe('−1.00%');
  });

  it('has no opinion when there is no threshold to measure against', () => {
    const pizza = alarm({
      sourceId: 'pizza',
      params: {},
      condition: { kind: 'state', field: 'status', states: ['spike'] },
    });
    expect(distanceFromThreshold(pizza, 3)).toBeUndefined();
  });

  it('refuses a missing or non-numeric reading rather than inventing zero', () => {
    expect(distanceFromThreshold(alarm(), null)).toBeUndefined();
    expect(distanceFromThreshold(alarm(), 'spike')).toBeUndefined();
  });

  it('refuses a zero threshold, which is a real setting with no denominator', () => {
    // A funding-rate alarm at 0 is ordinary; dividing by it is not.
    const atZero = alarm({
      sourceId: 'funding',
      params: {},
      condition: { kind: 'threshold', field: 'rate', op: 'above', value: 0 },
    });
    expect(distanceFromThreshold(atZero, 0.05)).toBeUndefined();
  });
});
