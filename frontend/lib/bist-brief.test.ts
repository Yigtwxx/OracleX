import { beforeEach, describe, expect, it } from 'vitest';

import type { ViopContract } from '@/lib/bist-api';
import {
  BIST_BRIEF_STORAGE_KEY,
  DEFAULT_BIST_BRIEF,
  MAX_BIST_BRIEF,
  addBistSlot,
  normalizeCode,
  readBistBrief,
  sanitizeSlots,
  setBistSlot,
  slotKey,
  bandPosition,
  pickViopContract,
  rangeBand,
  rsiBand,
  searchInstruments,
  sharpeBand,
  volumeBand,
  writeBistBrief,
  type BistBriefSlot,
  type BistInstrument,
} from './bist-brief';

/** A `Storage` that lives in a Map — vitest runs in node, with no DOM. */
function memoryStorage(seed: Record<string, string> = {}): Storage {
  const map = new Map(Object.entries(seed));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => void map.set(key, value),
  } as Storage;
}

const stock = (code: string): BistBriefSlot => ({ kind: 'stock', code });
const fund = (code: string): BistBriefSlot => ({ kind: 'fund', code });

describe('normalizeCode', () => {
  it('folds both Turkish i forms onto the ASCII the exchange actually uses', () => {
    // 'ı'.toUpperCase() and 'i'.toUpperCase() disagree across locales; the
    // ticker is ISCTR in every one of them.
    expect(normalizeCode('isctr')).toBe('ISCTR');
    expect(normalizeCode('ısctr')).toBe('ISCTR');
    expect(normalizeCode('İSCTR')).toBe('ISCTR');
  });

  it('strips punctuation and whitespace', () => {
    expect(normalizeCode('  thyao. ')).toBe('THYAO');
    expect(normalizeCode('BIST:ASELS')).toBe('BISTASELS');
  });

  it('returns an empty string for input with nothing usable in it', () => {
    expect(normalizeCode('   ')).toBe('');
    expect(normalizeCode('—')).toBe('');
  });
});

describe('sanitizeSlots', () => {
  it('keeps a share and a fund that share a code as two separate slots', () => {
    const out = sanitizeSlots([stock('TI7'), fund('TI7')]);
    expect(out).toHaveLength(2);
    expect(out?.map(slotKey)).toEqual(['stock:TI7', 'fund:TI7']);
  });

  it('drops a repeat of the same instrument', () => {
    expect(sanitizeSlots([stock('THYAO'), stock('thyao')])).toEqual([stock('THYAO')]);
  });

  it('caps at the slot count', () => {
    const many = Array.from({ length: 6 }, (_, i) => stock(`AAA${i}`));
    expect(sanitizeSlots(many)).toHaveLength(MAX_BIST_BRIEF);
  });

  it('rejects entries that are not slots at all', () => {
    expect(sanitizeSlots(['THYAO', 42, null, { kind: 'crypto', code: 'BTC' }])).toBeNull();
    expect(sanitizeSlots('THYAO')).toBeNull();
  });
});

describe('readBistBrief / writeBistBrief', () => {
  let storage: Storage;
  beforeEach(() => {
    storage = memoryStorage();
  });

  it('falls back to the default when nothing is stored', () => {
    expect(readBistBrief(storage)).toEqual([...DEFAULT_BIST_BRIEF]);
  });

  it('falls back rather than throwing on unparseable storage', () => {
    expect(readBistBrief(memoryStorage({ [BIST_BRIEF_STORAGE_KEY]: '{oops' }))).toEqual([
      ...DEFAULT_BIST_BRIEF,
    ]);
  });

  it('round-trips a chosen list', () => {
    writeBistBrief([stock('EREGL'), fund('DFI')], storage);
    expect(readBistBrief(storage)).toEqual([stock('EREGL'), fund('DFI')]);
  });

  it('remembers an emptied board instead of restoring the default', () => {
    // A reader who removed all three slots meant it; putting THYAO back on
    // every reload would be the board overruling them.
    writeBistBrief([], storage);
    expect(readBistBrief(storage)).toEqual([]);
  });
});

describe('setBistSlot', () => {
  const base = [stock('THYAO'), stock('ASELS'), fund('TI7')];

  it('replaces one position', () => {
    expect(setBistSlot(base, 1, stock('EREGL'))).toEqual([
      stock('THYAO'),
      stock('EREGL'),
      fund('TI7'),
    ]);
  });

  it('swaps rather than duplicating when the instrument is already on the board', () => {
    const out = setBistSlot(base, 2, stock('THYAO'));
    expect(out).toHaveLength(3);
    // Slot 2 held the fund, so it takes the position THYAO vacated.
    expect(out.map(slotKey)).toEqual(['fund:TI7', 'stock:ASELS', 'stock:THYAO']);
  });

  it('removes a position on null', () => {
    expect(setBistSlot(base, 0, null)).toEqual([stock('ASELS'), fund('TI7')]);
  });

  it('removing the last remaining slot leaves an empty board', () => {
    expect(setBistSlot([stock('THYAO')], 0, null)).toEqual([]);
  });
});

describe('addBistSlot', () => {
  it('appends when there is room', () => {
    expect(addBistSlot([stock('THYAO')], fund('DFI'))).toEqual([stock('THYAO'), fund('DFI')]);
  });

  it('refuses past the cap', () => {
    const full = [stock('A'), stock('B'), stock('C')];
    expect(addBistSlot(full, stock('D'))).toEqual(full);
  });

  it('refuses a duplicate but allows the same code on the other board', () => {
    expect(addBistSlot([stock('TI7')], stock('ti7'))).toEqual([stock('TI7')]);
    expect(addBistSlot([stock('TI7')], fund('TI7'))).toHaveLength(2);
  });
});

describe('searchInstruments', () => {
  const options: BistInstrument[] = [
    { kind: 'stock', code: 'ISCTR', name: 'TÜRKİYE İŞ BANKASI A.Ş.' },
    { kind: 'stock', code: 'THYAO', name: 'TÜRK HAVA YOLLARI A.O.' },
    { kind: 'fund', code: 'TI7', name: 'İŞ PORTFÖY DENGELİ DEĞİŞKEN FON' },
    { kind: 'fund', code: 'DFI', name: 'ATLAS PORTFÖY SERBEST FON' },
  ];

  it('puts an exact ticker above a fund whose title merely contains it', () => {
    const out = searchInstruments(options, 'ISCTR');
    expect(out[0].code).toBe('ISCTR');
  });

  it('ranks a code prefix above a name match', () => {
    const out = searchInstruments(options, 'TI');
    expect(out[0].code).toBe('TI7');
  });

  it('matches Turkish capitals that toLowerCase would break', () => {
    // 'İŞ'.toLowerCase() leaves a combining dot; the fold has to survive it.
    const out = searchInstruments(options, 'iş portföy');
    expect(out.map((row) => row.code)).toContain('TI7');
  });

  it('searches both boards at once', () => {
    const out = searchInstruments(options, 'portföy');
    expect(out.map((row) => row.kind)).toEqual(['fund', 'fund']);
  });

  it('returns the head of the list when nothing is typed', () => {
    expect(searchInstruments(options, '   ', 2)).toEqual(options.slice(0, 2));
  });

  it('honours the limit', () => {
    expect(searchInstruments(options, 'a', 1)).toHaveLength(1);
  });
});

describe('reading bands', () => {
  it('reads an overbought RSI as a warning, not as strength', () => {
    // The price rose to get there; the label is about what happens next.
    expect(rsiBand(79)).toEqual({ label: 'aşırı alım', tone: 'down' });
    expect(rsiBand(22)).toEqual({ label: 'aşırı satım', tone: 'up' });
    expect(rsiBand(50)).toEqual({ label: 'nötr', tone: 'neutral' });
    expect(rsiBand(null)).toBeNull();
    expect(rsiBand(Number.NaN)).toBeNull();
  });

  it('does not call an ordinary session busy', () => {
    expect(volumeBand(1.2)?.label).toBe('normal');
    expect(volumeBand(1.5)?.label).toBe('yoğun');
    expect(volumeBand(2.4)?.label).toBe('ağır');
    expect(volumeBand(0.4)?.label).toBe('ince');
    expect(volumeBand(0)).toBeNull();
  });

  it('names the extremes of the yearly range', () => {
    expect(rangeBand(0.95)?.label).toBe('zirveye yakın');
    expect(rangeBand(0.05)?.label).toBe('dibe yakın');
    expect(rangeBand(0.5)?.tone).toBe('neutral');
    expect(rangeBand(null)).toBeNull();
  });

  it('flags a fund that took risk to trail the risk-free rate', () => {
    expect(sharpeBand(-2.03)).toEqual({ label: 'risksiz getirinin altında', tone: 'down' });
    expect(sharpeBand(1.4)?.tone).toBe('up');
    expect(sharpeBand(null)).toBeNull();
  });
});

describe('bandPosition', () => {
  it('measures where the price sits between two bounds', () => {
    expect(bandPosition(150, 100, 200)).toBeCloseTo(0.5, 10);
    expect(bandPosition(100, 100, 200)).toBe(0);
    expect(bandPosition(200, 100, 200)).toBe(1);
  });

  it('refuses to draw a bar from half a measurement', () => {
    expect(bandPosition(150, null, 200)).toBeNull();
    expect(bandPosition(null, 100, 200)).toBeNull();
    // Price outside the band it was measured against.
    expect(bandPosition(250, 100, 200)).toBeNull();
    // Bounds that do not bracket anything.
    expect(bandPosition(150, 200, 100)).toBeNull();
  });
});

describe('pickViopContract', () => {
  const contract = (
    underlying: string,
    expiry: string,
    open_interest: number | null
  ): ViopContract => ({
    contract: `${underlying} (${expiry}) Vadeli`,
    underlying,
    expiry,
    physical: true,
    expiry_date: '2026-08-31',
    kind: 'future',
    last: 10,
    change_pct: 0.01,
    high: 11,
    low: 9,
    open_interest,
    open_interest_change: 100,
    settlement: 10,
    previous_settlement: 10,
    traded_at: '11:04:57',
  });

  it('picks the contract carrying the position, not the first row', () => {
    const rows = [
      contract('ISCTR', '31 Eki 26', 1_000),
      contract('ISCTR', '30 Ara 26', 9_000),
      contract('SASA', '30 Eyl 26', 50_000),
    ];
    expect(pickViopContract(rows, 'ISCTR')?.expiry).toBe('30 Ara 26');
  });

  it('answers null for an underlying with no listed contract', () => {
    expect(pickViopContract([contract('ISCTR', '31 Eki 26', 10)], 'ASELS')).toBeNull();
    expect(pickViopContract([], 'ISCTR')).toBeNull();
    expect(pickViopContract(undefined, 'ISCTR')).toBeNull();
  });

  it('matches the underlying through the same normalisation the slots use', () => {
    expect(pickViopContract([contract('ISCTR', '31 Eki 26', 10)], 'ısctr')?.underlying).toBe(
      'ISCTR'
    );
  });

  it('still returns a row when every contract has null open interest', () => {
    const rows = [contract('ISCTR', '31 Eki 26', null)];
    expect(pickViopContract(rows, 'ISCTR')?.expiry).toBe('31 Eki 26');
  });
});
