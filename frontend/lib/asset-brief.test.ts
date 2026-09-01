import { describe, expect, it } from 'vitest';
import type { AssetBrief } from '@/lib/api';
import {
  BRIEF_STORAGE_KEY,
  DEFAULT_BRIEF_SYMBOLS,
  MAX_BRIEF_SYMBOLS,
  addSymbol,
  baseSymbol,
  changeTone,
  formatCompact,
  formatSignedPercent,
  fundingReading,
  normalizeSymbol,
  rangePosition,
  readBriefSymbols,
  relativeVolumeLabel,
  rsiLabel,
  sanitizeSymbols,
  SURGE_THRESHOLD_PCT,
  setSlot,
  surgeHue,
  writeBriefSymbols,
} from './asset-brief';

/** A localStorage stand-in, plus a mode where every access throws. */
function fakeStorage(initial: Record<string, string> = {}, throws = false): Storage {
  const map = new Map(Object.entries(initial));
  const guard = () => {
    if (throws) throw new Error('storage is blocked');
  };
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    getItem: (key: string) => {
      guard();
      return map.get(key) ?? null;
    },
    setItem: (key: string, value: string) => {
      guard();
      map.set(key, value);
    },
    removeItem: (key: string) => {
      map.delete(key);
    },
  } as Storage;
}

const stored = (symbols: unknown) => ({ [BRIEF_STORAGE_KEY]: JSON.stringify({ v: 1, symbols }) });

describe('normalizeSymbol', () => {
  it('uppercases, trims and strips the social-feed dollar prefix', () => {
    expect(normalizeSymbol('  $nvda ')).toBe('NVDA');
    expect(normalizeSymbol('binance:btcusdt')).toBe('BINANCE:BTCUSDT');
  });

  it('returns an empty string for input with nothing in it', () => {
    expect(normalizeSymbol('  $$ ')).toBe('');
  });
});

describe('sanitizeSymbols', () => {
  it('drops duplicates that differ only in case or prefix', () => {
    expect(sanitizeSymbols(['btc', 'BTC', '$btc'])).toEqual(['BTC']);
  });

  it('caps the list at the number of slots that fit', () => {
    expect(sanitizeSymbols(['A', 'B', 'C', 'D'])).toEqual(['A', 'B', 'C']);
    expect(MAX_BRIEF_SYMBOLS).toBe(3);
  });

  it('ignores non-string entries rather than rendering them', () => {
    expect(sanitizeSymbols(['BTC', 42, null, { symbol: 'ETH' }, 'eth'])).toEqual(['BTC', 'ETH']);
  });

  it('returns null when nothing usable survives', () => {
    expect(sanitizeSymbols([])).toBeNull();
    expect(sanitizeSymbols(['  ', '$'])).toBeNull();
    expect(sanitizeSymbols('BTC')).toBeNull();
    expect(sanitizeSymbols(undefined)).toBeNull();
  });
});

describe('readBriefSymbols', () => {
  it('reads what was stored', () => {
    expect(readBriefSymbols(fakeStorage(stored(['sol', 'AAPL'])))).toEqual(['SOL', 'AAPL']);
  });

  it('falls back to the default for an empty store', () => {
    expect(readBriefSymbols(fakeStorage())).toEqual(DEFAULT_BRIEF_SYMBOLS);
  });

  it('falls back rather than throwing on malformed JSON', () => {
    expect(readBriefSymbols(fakeStorage({ [BRIEF_STORAGE_KEY]: '{oh no' }))).toEqual(
      DEFAULT_BRIEF_SYMBOLS
    );
  });

  it('falls back when the stored shape is from another version', () => {
    expect(readBriefSymbols(fakeStorage({ [BRIEF_STORAGE_KEY]: '{"symbols":"BTC"}' }))).toEqual(
      DEFAULT_BRIEF_SYMBOLS
    );
    expect(readBriefSymbols(fakeStorage(stored([])))).toEqual(DEFAULT_BRIEF_SYMBOLS);
  });

  it('falls back when the browser blocks storage entirely', () => {
    expect(readBriefSymbols(fakeStorage({}, true))).toEqual(DEFAULT_BRIEF_SYMBOLS);
  });
});

describe('writeBriefSymbols', () => {
  it('round-trips through the store, normalised', () => {
    const store = fakeStorage();
    writeBriefSymbols(['btc', 'nvda'], store);
    expect(readBriefSymbols(store)).toEqual(['BTC', 'NVDA']);
  });

  it('refuses to persist an empty list over a good one', () => {
    const store = fakeStorage(stored(['BTC']));
    writeBriefSymbols([], store);
    expect(readBriefSymbols(store)).toEqual(['BTC']);
  });

  it('does not throw when the store refuses the write', () => {
    expect(() => writeBriefSymbols(['BTC'], fakeStorage({}, true))).not.toThrow();
  });
});

describe('setSlot', () => {
  const slots = ['BTC', 'ETH', 'NVDA'];

  it('replaces the named slot', () => {
    expect(setSlot(slots, 1, 'sol')).toEqual(['BTC', 'SOL', 'NVDA']);
  });

  it('swaps rather than duplicating when the symbol is already on the board', () => {
    expect(setSlot(slots, 2, 'BTC')).toEqual(['NVDA', 'ETH', 'BTC']);
  });

  it('removes the slot when given null', () => {
    expect(setSlot(slots, 0, null)).toEqual(['ETH', 'NVDA']);
  });

  it('leaves the board alone for input that normalises to nothing', () => {
    expect(setSlot(slots, 0, '  ')).toEqual(slots);
  });
});

describe('addSymbol', () => {
  it('appends while there is room', () => {
    expect(addSymbol(['BTC'], 'eth')).toEqual(['BTC', 'ETH']);
  });

  it('refuses a duplicate', () => {
    expect(addSymbol(['BTC'], '$btc')).toEqual(['BTC']);
  });

  it('refuses once the slots are full', () => {
    const full = ['BTC', 'ETH', 'NVDA'];
    expect(addSymbol(full, 'SOL')).toEqual(full);
  });
});

describe('rsiLabel', () => {
  it('names the extremes on the side a reader would act from', () => {
    expect(rsiLabel(72)).toEqual({ label: 'Overbought', tone: 'down' });
    expect(rsiLabel(28)).toEqual({ label: 'Oversold', tone: 'up' });
  });

  it('is inclusive at the band edges', () => {
    expect(rsiLabel(70)?.label).toBe('Overbought');
    expect(rsiLabel(30)?.label).toBe('Oversold');
    expect(rsiLabel(55)?.label).toBe('Firm');
    expect(rsiLabel(45)?.label).toBe('Soft');
  });

  it('calls the middle neutral', () => {
    expect(rsiLabel(50)).toEqual({ label: 'Neutral', tone: 'neutral' });
  });

  it('returns null for a reading that was not taken', () => {
    expect(rsiLabel(null)).toBeNull();
    expect(rsiLabel(Number.NaN)).toBeNull();
  });
});

describe('relativeVolumeLabel', () => {
  it('calls an ordinary session ordinary', () => {
    expect(relativeVolumeLabel(1.2)?.label).toBe('Normal');
  });

  it('separates busy from heavy', () => {
    expect(relativeVolumeLabel(1.5)?.label).toBe('Busy');
    expect(relativeVolumeLabel(2.4)?.label).toBe('Heavy');
  });

  it('names a thin session', () => {
    expect(relativeVolumeLabel(0.4)?.label).toBe('Thin');
  });

  it('returns null rather than a label for an impossible ratio', () => {
    expect(relativeVolumeLabel(null)).toBeNull();
    expect(relativeVolumeLabel(0)).toBeNull();
    expect(relativeVolumeLabel(-1)).toBeNull();
  });
});

describe('fundingReading', () => {
  it('converts to basis points and names who pays', () => {
    expect(fundingReading(0.0001, false)).toEqual({
      bps: 1,
      label: 'Longs pay',
      tone: 'down',
      extreme: false,
    });
  });

  it('colours crowded longs as the bearish side, not by the sign', () => {
    expect(fundingReading(0.0005, true)?.tone).toBe('down');
    expect(fundingReading(-0.0005, false)?.tone).toBe('up');
  });

  it('distinguishes a flat rate from an absent one', () => {
    expect(fundingReading(0, false)).toEqual({
      bps: 0,
      label: 'Flat',
      tone: 'neutral',
      extreme: false,
    });
    expect(fundingReading(null, null)).toBeNull();
  });
});

describe('changeTone', () => {
  it('treats an unchanged and an unknown price the same way — as no claim', () => {
    expect(changeTone(0)).toBe('neutral');
    expect(changeTone(null)).toBe('neutral');
  });

  it('follows the sign otherwise', () => {
    expect(changeTone(0.1)).toBe('up');
    expect(changeTone(-0.1)).toBe('down');
  });
});

describe('rangePosition', () => {
  const brief = (over: Partial<AssetBrief>): AssetBrief =>
    ({ price: 100, support: 90, resistance: 110, ...over }) as AssetBrief;

  it('places price between the bounds', () => {
    expect(rangePosition(brief({}))).toBeCloseTo(0.5);
    expect(rangePosition(brief({ price: 92 }))).toBeCloseTo(0.1);
  });

  it('refuses to draw a bar from half a measurement', () => {
    expect(rangePosition(brief({ support: null }))).toBeNull();
    expect(rangePosition(brief({ resistance: null }))).toBeNull();
  });

  it('refuses when price has left the band it was measured against', () => {
    expect(rangePosition(brief({ price: 120 }))).toBeNull();
    expect(rangePosition(brief({ price: 80 }))).toBeNull();
  });

  it('refuses an inverted band', () => {
    expect(rangePosition(brief({ support: 110, resistance: 90 }))).toBeNull();
  });
});

describe('formatSignedPercent', () => {
  it('always carries the sign', () => {
    expect(formatSignedPercent(2.345)).toBe('+2.35%');
    expect(formatSignedPercent(-2.345)).toBe('-2.35%');
    expect(formatSignedPercent(0)).toBe('+0.00%');
  });

  it('renders a missing reading as a dash, not as zero', () => {
    expect(formatSignedPercent(null)).toBe('—');
    expect(formatSignedPercent(Number.NaN)).toBe('—');
  });
});

describe('formatCompact', () => {
  it('scales to the unit the number belongs in', () => {
    expect(formatCompact(1_234_000_000_000)).toBe('$1.23T');
    expect(formatCompact(1_234_000_000)).toBe('$1.23B');
    expect(formatCompact(1_234_000)).toBe('$1.23M');
    expect(formatCompact(1_234)).toBe('$1.2K');
    expect(formatCompact(123)).toBe('$123');
  });

  it('drops the currency prefix for share counts', () => {
    expect(formatCompact(45_000_000, false)).toBe('45.00M');
  });

  it('scales negatives by magnitude', () => {
    expect(formatCompact(-1_500_000)).toBe('$-1.50M');
  });

  it('renders a missing reading as a dash', () => {
    expect(formatCompact(null)).toBe('—');
  });
});

describe('surgeHue', () => {
  it('lights the rim on a run', () => {
    expect(surgeHue(SURGE_THRESHOLD_PCT, 0)?.hue).toBe('var(--up)');
    expect(surgeHue(SURGE_THRESHOLD_PCT, 0)?.direction).toBe('up');
    expect(surgeHue(24.6, 0)?.change).toBeCloseTo(24.6);
  });

  it('falls back to the week when the day is quiet', () => {
    // The case that put the week in here at all: BTC sat +10.2% on the week
    // with a 24h change of -0.16%, and the card stayed dark.
    const surge = surgeHue(-0.16, 10.2);
    expect(surge?.window).toBe('7d');
    expect(surge?.direction).toBe('up');
  });

  it('prefers the day when both windows qualify and they disagree', () => {
    // PYTH: -10.75% on the session inside a +11.4% week. The rim has to agree
    // with the figure printed largest, or it reads as a bug.
    const surge = surgeHue(-10.75, 11.4);
    expect(surge?.window).toBe('24h');
    expect(surge?.hue).toBe('var(--down)');
    expect(surge?.change).toBeCloseTo(-10.75);
  });

  it('leaves an ordinary card alone', () => {
    expect(surgeHue(9.9, 9.9)).toBeNull();
    expect(surgeHue(0, 0)).toBeNull();
  });

  it('lights a fall of the same size, in the other hue', () => {
    // A 10% drawdown is the same size of news as a 10% run, so the band is
    // symmetric and the hue — not the threshold — is what tells them apart.
    expect(surgeHue(-SURGE_THRESHOLD_PCT, 0)?.hue).toBe('var(--down)');
    expect(surgeHue(-12, 0)?.direction).toBe('down');
    expect(surgeHue(0, -12)?.window).toBe('7d');
    expect(surgeHue(-9.9, -9.9)).toBeNull();
  });

  it('returns null for a card whose moves could not be measured', () => {
    expect(surgeHue(null, null)).toBeNull();
    expect(surgeHue(Number.NaN, Number.NaN)).toBeNull();
    // A missing day must not hide a week that qualifies.
    expect(surgeHue(null, 14)?.window).toBe('7d');
  });
});

describe('baseSymbol', () => {
  it('strips the quote currency from a pair', () => {
    expect(baseSymbol('BTCUSDT')).toBe('BTC');
    expect(baseSymbol('ETHUSDC')).toBe('ETH');
    expect(baseSymbol('SOLFDUSD')).toBe('SOL');
  });

  it('strips the venue prefix too', () => {
    expect(baseSymbol('BINANCE:BTCUSDT')).toBe('BTC');
    expect(baseSymbol('NASDAQ:NVDA')).toBe('NVDA');
  });

  it('prefers the longer quote, so USDT is not read as USD', () => {
    // `USD` first would turn BTCUSDT into BTCT and ask a logo host for a coin
    // that does not exist.
    expect(baseSymbol('BTCUSDT')).not.toBe('BTCT');
  });

  it('leaves an equity ticker alone', () => {
    expect(baseSymbol('nvda')).toBe('NVDA');
    expect(baseSymbol('$AAPL')).toBe('AAPL');
  });

  it('never strips a ticker down to nothing', () => {
    expect(baseSymbol('USD')).toBe('USD');
    expect(baseSymbol('USDT')).toBe('USDT');
  });
});
