import { describe, expect, it } from 'vitest';

import {
  CAPITAL_ACTION_NOTE,
  EMPTY,
  NBSP,
  SESSION_LABEL,
  formatCompact,
  formatCompactTry,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
  formatSignedPercent,
  formatTry,
  isLikelyCapitalAction,
  isRealLoss,
  realReturnNote,
  sessionState,
  toneClass,
  turkishFold,
  turkishIncludes,
  type FramedReturn,
} from '@/lib/bist-format';

describe('numbers', () => {
  it('uses the Turkish separators', () => {
    // `1.234,56` is one thousand two hundred. An English-reading parser takes
    // the same string as 1.23, which is the failure this pins.
    expect(formatNumber(1234.56)).toBe('1.234,56');
    expect(formatNumber(1_000_000, 0)).toBe('1.000.000');
  });

  it('renders the sentinel rather than a zero for missing input', () => {
    expect(formatNumber(null)).toBe(EMPTY);
    expect(formatNumber(undefined)).toBe(EMPTY);
    expect(formatNumber(Number.NaN)).toBe(EMPTY);
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe(EMPTY);
  });

  it('puts the lira symbol after the number', () => {
    expect(formatTry(304.5)).toBe(`304,50${NBSP}₺`);
    expect(formatTry(null)).toBe(EMPTY);
  });
});

describe('compact magnitudes', () => {
  it('abbreviates in Turkish, not in English', () => {
    // `mr` for milyar rather than `B`: the English B means billion, the Turkish
    // milyar starts with the same letter, and confusing them is a factor of
    // a thousand.
    expect(formatCompact(1_841_000_000_000)).toBe(`1,8${NBSP}tn`);
    expect(formatCompact(720_139_875_793)).toBe(`720,1${NBSP}mr`);
    expect(formatCompact(4_882_537)).toBe(`4,9${NBSP}mn`);
    expect(formatCompact(7_271)).toBe(`7,3${NBSP}bin`);
  });

  it('leaves small numbers uncompacted', () => {
    expect(formatCompact(842)).toBe('842');
  });

  it('keeps the sign on negatives', () => {
    expect(formatCompact(-4_882_537)).toBe(`-4,9${NBSP}mn`);
  });

  it('joins figure and unit with a non-breaking space', () => {
    // U+00A0, so a market-cap cell never wraps with the unit orphaned below.
    expect(formatCompact(4_882_537)).toContain(NBSP);
    expect(formatCompact(4_882_537)).not.toContain(' ');
  });

  it('appends the currency for capitalisation columns', () => {
    expect(formatCompactTry(1_841_100_000_000)).toBe(`1,8${NBSP}tn${NBSP}₺`);
    expect(formatCompactTry(null)).toBe(EMPTY);
  });
});

describe('percentages', () => {
  it('puts the sign before the number, as Turkish does', () => {
    expect(formatPercent(0.1234)).toBe('%12,3');
    expect(formatPercent(-0.0092)).toBe('%-0,9');
  });

  it('takes a fraction, never an already-multiplied percentage', () => {
    // 1.48 is +148%, which is what the API sends for a fund that more than
    // doubled. Reading it as 1.48% would be the same bug in reverse.
    expect(formatPercent(1.48)).toBe('%148,0');
  });

  it('marks gains explicitly when signed', () => {
    expect(formatSignedPercent(0.0219)).toBe('+%2,2');
    expect(formatSignedPercent(-0.0219)).toBe('%-2,2');
    expect(formatSignedPercent(0)).toBe('%0,0');
  });

  it('is the sentinel for missing input', () => {
    expect(formatPercent(null)).toBe(EMPTY);
    expect(formatSignedPercent(undefined)).toBe(EMPTY);
  });
});

describe('toneClass', () => {
  it('stays neutral for zero and for unknown', () => {
    // A missing figure must not be painted as a loss.
    expect(toneClass(0)).toBe('text-fg-muted');
    expect(toneClass(null)).toBe('text-fg-muted');
  });

  it('colours by direction', () => {
    expect(toneClass(0.01)).toBe('text-up');
    expect(toneClass(-0.01)).toBe('text-down');
  });
});

describe('framed returns', () => {
  const framed = (nominal: number, real: number | null): FramedReturn => ({
    nominal,
    real,
    usd: null,
  });

  it('explains an uncomputable real return rather than showing zero', () => {
    expect(realReturnNote(framed(1.0, null))).toContain('hesaplanamadı');
    expect(realReturnNote(framed(1.0, 0.3))).not.toContain('hesaplanamadı');
    expect(realReturnNote(null)).toBe('Veri yok.');
  });

  it('flags a nominal gain that is a real loss', () => {
    // The one fact this realm exists to surface.
    expect(isRealLoss(framed(0.2, -0.09))).toBe(true);
    expect(isRealLoss(framed(0.2, 0.05))).toBe(false);
    expect(isRealLoss(framed(-0.2, -0.4))).toBe(false);
    expect(isRealLoss(framed(0.2, null))).toBe(false);
  });
});

describe('dates', () => {
  it('uses Turkish month abbreviations', () => {
    expect(formatDate('2026-08-27')).toBe('27 Ağu 2026');
    expect(formatDate('2026-01-05')).toBe('5 Oca 2026');
  });

  it('appends a 24-hour clock', () => {
    expect(formatDateTime('2026-08-27T15:06:10')).toBe('27 Ağu 2026 15:06');
    expect(formatDateTime('2026-08-27T09:05:00')).toBe('27 Ağu 2026 09:05');
  });

  it('is the sentinel for an unparseable value', () => {
    expect(formatDate(null)).toBe(EMPTY);
    expect(formatDate('not a date')).toBe(EMPTY);
    expect(formatDateTime(undefined)).toBe(EMPTY);
  });
});

describe('formatRelative', () => {
  const now = new Date('2026-08-27T15:00:00Z');

  it('reports in Turkish across the thresholds', () => {
    expect(formatRelative('2026-08-27T14:59:30Z', now)).toBe('az önce');
    expect(formatRelative('2026-08-27T14:30:00Z', now)).toBe('30 dk önce');
    expect(formatRelative('2026-08-27T11:00:00Z', now)).toBe('4 sa önce');
    expect(formatRelative('2026-08-25T15:00:00Z', now)).toBe('2 gün önce');
  });

  it('never reports a negative age', () => {
    // Clock skew between the browser and the server should not render as
    // "-3 dk önce".
    expect(formatRelative('2026-08-27T15:05:00Z', now)).toBe('az önce');
  });
});

describe('sessionState', () => {
  // Istanbul is UTC+3 and does not observe daylight saving, so a UTC instant
  // maps to a fixed local hour.
  it('knows the auction window', () => {
    expect(sessionState(new Date('2026-08-27T06:00:00Z'))).toBe('pre'); // 09:00
    expect(sessionState(new Date('2026-08-27T07:30:00Z'))).toBe('open'); // 10:30
    expect(sessionState(new Date('2026-08-27T15:30:00Z'))).toBe('closed'); // 18:30
  });

  it('treats the boundaries as open and closed respectively', () => {
    expect(sessionState(new Date('2026-08-27T07:00:00Z'))).toBe('open'); // 10:00
    expect(sessionState(new Date('2026-08-27T15:00:00Z'))).toBe('closed'); // 18:00
  });

  it('recognises the weekend', () => {
    // 2026-08-29 is a Saturday. Mid-session hours must not read as open.
    expect(sessionState(new Date('2026-08-29T09:00:00Z'))).toBe('weekend');
    expect(sessionState(new Date('2026-08-30T09:00:00Z'))).toBe('weekend');
  });

  it('has a label for every state', () => {
    for (const state of ['pre', 'open', 'closed', 'weekend'] as const) {
      expect(SESSION_LABEL[state]).toBeTruthy();
    }
  });
});

describe('turkish folding', () => {
  it('folds the dotted capital to a plain i', () => {
    // `'KESİCİ'.toLowerCase()` leaves a combining dot behind, so the two stop
    // comparing equal. The backend hit this in the restriction radar; the
    // frontend has to agree or the same query answers differently per side.
    expect(turkishFold('KESİCİ')).toBe('kesici');
    expect('KESİCİ'.toLowerCase()).not.toBe('kesici');
  });

  it('folds the dotless capital to a dotless i', () => {
    expect(turkishFold('ISI')).toBe('ısı');
  });

  it('matches a company name typed in either case', () => {
    expect(turkishIncludes('TÜRKİYE İŞ BANKASI', 'iş bankası')).toBe(true);
    expect(turkishIncludes('Türkiye İş Bankası', 'İŞ BANKASI')).toBe(true);
    expect(turkishIncludes('GARANTİ BANKASI', 'akbank')).toBe(false);
  });
});

describe('isLikelyCapitalAction', () => {
  it('accepts moves inside the daily limit as real trading', () => {
    // Turkey caps most shares at ±10% a session, so anything inside that band
    // is a price move and nothing else.
    expect(isLikelyCapitalAction(0.1)).toBe(false);
    expect(isLikelyCapitalAction(-0.1)).toBe(false);
    expect(isLikelyCapitalAction(0.14)).toBe(false);
  });

  it('flags a move that could not have happened through trading', () => {
    // SDT Uzay ve Savunma printed -%90,4 the day this was written. It did a
    // ten-for-one bonus issue; the quote source reports the unadjusted gap as
    // an ordinary change and a losers list reads it as a collapse.
    expect(isLikelyCapitalAction(-0.904)).toBe(true);
    expect(isLikelyCapitalAction(0.5)).toBe(true);
  });

  it('says nothing about a missing figure', () => {
    expect(isLikelyCapitalAction(null)).toBe(false);
    expect(isLikelyCapitalAction(undefined)).toBe(false);
  });

  it('has a note that names the cause rather than just warning', () => {
    expect(CAPITAL_ACTION_NOTE).toContain('bedelsiz');
    expect(CAPITAL_ACTION_NOTE).toContain('Fiyat düşüşü değil');
  });
});
