import { describe, expect, it } from 'vitest';
import { evaluateAlarm } from './evaluate';
import { DEFAULT_COOLDOWN_MS, SEEN_KEYS_LIMIT, type Alarm, type Reading } from './types';

const NOW = Date.parse('2026-08-24T12:00:00.000Z');

function alarm(overrides: Partial<Alarm> = {}): Alarm {
  return {
    id: 'a1',
    sourceId: 'price',
    params: { symbol: 'BTCUSDT' },
    condition: { kind: 'threshold', field: 'price', op: 'above', value: 100 },
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

function reading(overrides: Partial<Reading> = {}): Reading {
  return {
    key: 'price:BTCUSDT',
    values: { price: 120 },
    stale: false,
    display: '$120,00',
    ...overrides,
  };
}

describe('evaluateAlarm — gates that prevent a false alarm', () => {
  it('fires when the threshold is cleared', () => {
    const decision = evaluateAlarm(alarm(), reading(), NOW);
    expect(decision.action).toBe('trigger');
  });

  it('stays quiet on a disabled alarm', () => {
    expect(evaluateAlarm(alarm({ enabled: false }), reading(), NOW).action).toBe('none');
  });

  it('does not fire on a cached replay', () => {
    // An outage would otherwise re-fire every alarm on the same frozen numbers
    // for as long as it lasted.
    expect(evaluateAlarm(alarm(), reading({ stale: true }), NOW).action).toBe('none');
  });

  it.each(['unavailable', 'insufficient_data'])('does not fire on status %s', (status) => {
    // The macro endpoints never answer 503; a gap arrives in-band.
    expect(evaluateAlarm(alarm(), reading({ status }), NOW).action).toBe('none');
  });

  it('treats a null reading as no reading, not as zero', () => {
    // The regression this guards: a "below" alarm firing the instant a source
    // goes dark, because null coerced to 0 is below every positive threshold.
    const below = alarm({
      condition: { kind: 'threshold', field: 'price', op: 'below', value: 100 },
    });
    expect(evaluateAlarm(below, reading({ values: { price: null } }), NOW).action).toBe('none');
  });

  it('ignores a field that is present but not a finite number', () => {
    expect(evaluateAlarm(alarm(), reading({ values: { price: Number.NaN } }), NOW).action).toBe(
      'none'
    );
  });

  it('fires on exact equality', () => {
    expect(evaluateAlarm(alarm(), reading({ values: { price: 100 } }), NOW).action).toBe('trigger');
  });
});

describe('evaluateAlarm — repeat and cooldown', () => {
  it('a once alarm never fires twice', () => {
    const spent = alarm({ triggerCount: 1, armed: true });
    expect(evaluateAlarm(spent, reading(), NOW).action).toBe('none');
  });

  it('an always alarm stays quiet inside its cooldown', () => {
    const cooling = alarm({
      repeat: 'always',
      triggerCount: 1,
      lastTriggeredAt: new Date(NOW - 60_000).toISOString(),
    });
    expect(evaluateAlarm(cooling, reading(), NOW).action).toBe('none');
  });

  it('an always alarm fires again once the cooldown expires', () => {
    const cooled = alarm({
      repeat: 'always',
      triggerCount: 1,
      lastTriggeredAt: new Date(NOW - DEFAULT_COOLDOWN_MS - 1).toISOString(),
    });
    const decision = evaluateAlarm(cooled, reading(), NOW);
    expect(decision.action).toBe('trigger');
    if (decision.action === 'trigger') expect(decision.patch.triggerCount).toBe(2);
  });
});

describe('evaluateAlarm — hysteresis on a level', () => {
  const repeating = alarm({ repeat: 'always' });

  it('disarms itself when it fires', () => {
    const decision = evaluateAlarm(repeating, reading(), NOW);
    expect(decision.action === 'trigger' && decision.patch.armed).toBe(false);
  });

  it('a value hovering just past the threshold produces one trigger, not one per tick', () => {
    const disarmed = alarm({ repeat: 'always', armed: false, lastTriggeredAt: undefined });
    // 100.4 is past the threshold but inside the re-arm band, so it neither
    // fires nor clears the latch.
    expect(evaluateAlarm(disarmed, reading({ values: { price: 100.4 } }), NOW).action).toBe('none');
    expect(evaluateAlarm(disarmed, reading({ values: { price: 99.9 } }), NOW).action).toBe('none');
  });

  it('re-arms only once the value retreats past the band', () => {
    const disarmed = alarm({ repeat: 'always', armed: false });
    const decision = evaluateAlarm(disarmed, reading({ values: { price: 99 } }), NOW);
    expect(decision.action).toBe('rearm');
    if (decision.action === 'rearm') expect(decision.patch.armed).toBe(true);
  });
});

describe('evaluateAlarm — state conditions', () => {
  const pizza = alarm({
    sourceId: 'pizza',
    params: {},
    condition: { kind: 'state', field: 'status', states: ['elevated', 'spike'] },
  });

  it('fires when the server-computed status enters the watched set', () => {
    const decision = evaluateAlarm(
      pizza,
      reading({ values: { status: 'spike' }, key: 'pizza' }),
      NOW
    );
    expect(decision.action).toBe('trigger');
  });

  it('stays quiet for a status outside the set', () => {
    expect(
      evaluateAlarm(pizza, reading({ values: { status: 'normal' }, key: 'pizza' }), NOW).action
    ).toBe('none');
  });

  it('re-arms when the status leaves the set', () => {
    const disarmed = { ...pizza, armed: false };
    expect(
      evaluateAlarm(disarmed, reading({ values: { status: 'normal' }, key: 'pizza' }), NOW).action
    ).toBe('rearm');
  });
});

describe('evaluateAlarm — event-shaped readings', () => {
  const news = alarm({
    sourceId: 'news',
    params: {},
    repeat: 'always',
    condition: { kind: 'keyword', terms: ['fed', 'cpi'], matchIn: 'both' },
  });
  const headline = reading({
    key: 'news:42',
    eventShaped: true,
    values: { title: 'FED faiz kararını açıkladı', summary: '' },
    display: 'FED faiz kararını açıkladı',
  });

  it('matches case-insensitively', () => {
    expect(evaluateAlarm(news, headline, NOW).action).toBe('trigger');
  });

  it('records the key so the same item cannot fire twice', () => {
    const decision = evaluateAlarm(news, headline, NOW);
    expect(decision.action === 'trigger' && decision.patch.seenKeys).toContain('news:42');
  });

  it('stays quiet for an already-seen key', () => {
    const seen = { ...news, seenKeys: ['news:42'] };
    expect(evaluateAlarm(seen, headline, NOW).action).toBe('none');
  });

  it('bounds the dedupe ring', () => {
    const crowded = {
      ...news,
      seenKeys: Array.from({ length: SEEN_KEYS_LIMIT }, (_, i) => `old:${i}`),
    };
    const decision = evaluateAlarm(crowded, headline, NOW);
    expect(decision.action === 'trigger' && decision.patch.seenKeys?.length).toBe(SEEN_KEYS_LIMIT);
  });

  it('does not match a term that appears in neither field', () => {
    const quiet = {
      ...news,
      condition: { kind: 'keyword' as const, terms: ['nvidia'], matchIn: 'both' as const },
    };
    expect(evaluateAlarm(quiet, headline, NOW).action).toBe('none');
  });

  it('ignores blank terms rather than matching everything', () => {
    const blank = {
      ...news,
      condition: { kind: 'keyword' as const, terms: ['  '], matchIn: 'both' as const },
    };
    expect(evaluateAlarm(blank, headline, NOW).action).toBe('none');
  });

  it('an event-shaped threshold is deduped rather than latched', () => {
    // A liquidation alarm is a threshold, but every fill is its own event: the
    // latch would silence it after the first one.
    const liq = alarm({
      sourceId: 'liquidation',
      params: {},
      repeat: 'always',
      condition: { kind: 'threshold', field: 'amount_usd', op: 'above', value: 1_000_000 },
    });
    const first = reading({ key: 'liq:1', eventShaped: true, values: { amount_usd: 2_000_000 } });
    const second = reading({ key: 'liq:2', eventShaped: true, values: { amount_usd: 3_000_000 } });

    const one = evaluateAlarm(liq, first, NOW);
    expect(one.action).toBe('trigger');
    expect(one.action === 'trigger' && one.patch.armed).toBeUndefined();

    // A distinct fill fires again once the cooldown — the burst limiter, not
    // the latch — has elapsed.
    const after = { ...liq, ...(one.action === 'trigger' ? one.patch : {}) };
    expect(evaluateAlarm(after, second, NOW + liq.cooldownMs + 1).action).toBe('trigger');
  });
});

describe('evaluateAlarm — countdown', () => {
  const event = alarm({
    sourceId: 'macroEvent',
    params: {},
    condition: { kind: 'countdown', leadMinutes: 15 },
  });

  it('fires inside the lead window', () => {
    const decision = evaluateAlarm(
      event,
      reading({ key: 'ev:1', eventShaped: true, values: { minutesUntil: 10 } }),
      NOW
    );
    expect(decision.action).toBe('trigger');
  });

  it('stays quiet while the event is further out', () => {
    expect(
      evaluateAlarm(
        event,
        reading({ key: 'ev:1', eventShaped: true, values: { minutesUntil: 40 } }),
        NOW
      ).action
    ).toBe('none');
  });

  it('does not announce an event that already started', () => {
    expect(
      evaluateAlarm(
        event,
        reading({ key: 'ev:1', eventShaped: true, values: { minutesUntil: -5 } }),
        NOW
      ).action
    ).toBe('none');
  });
});
