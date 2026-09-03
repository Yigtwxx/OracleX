import { describe, expect, it } from 'vitest';

import type { RadarLevels, RadarResult, RadarRow, RadarVoice } from './bist-api';
import {
  depthNote,
  distanceTo,
  formatRr,
  levelMarks,
  memosPending,
  rejectionText,
  scoreTone,
  stanceTone,
  summaryLine,
  voiceLabel,
  voicesNote,
} from './bist-radar';

function levels(overrides: Partial<RadarLevels> = {}): RadarLevels {
  return {
    entry_low: 94,
    entry_high: 97,
    entry_mid: 95.5,
    stop: 91,
    target1: 108,
    target2: 115,
    rr: 2.7,
    atr: 3,
    price: 96,
    pullback_pct: 0.07,
    rsi: 45,
    rsi_divergence: null,
    volume_ratio: 0.7,
    structure: 'higher',
    zone_touches: 3,
    zone_source: 'support_zone',
    range_position: 0.7,
    ema_fast: 98,
    ema_slow: 95.5,
    high20: 103,
    sma50_gap: 0.1,
    ...overrides,
  };
}

function row(overrides: Partial<RadarRow> = {}): RadarRow {
  return {
    ticker: 'TEST',
    symbol: 'BIST:TEST',
    name: 'Test',
    sector: 'Sanayi',
    sector_class: 'industrial',
    price: 100,
    change_pct: 0,
    market_cap: 1e9,
    score_technical: 70,
    score_fundamental: 50,
    fundamental_coverage: 1,
    fundamental_depth: 'full',
    score_total: 62,
    rr: 2,
    vetoes: [],
    stage_reached: 'scored',
    rejected_reason: 'score_below_threshold',
    rejected_label: 'Toplam puan 60 altında',
    ...overrides,
  };
}

function result(overrides: Partial<RadarResult> = {}): RadarResult {
  return {
    horizon: 'swing',
    horizon_label: 'Swing',
    scanned_at: '2026-09-02T12:00:00Z',
    duration_seconds: 60,
    delay_minutes: 15,
    universe_size: 100,
    fundamental_depth: 'full',
    fundamentals_covered: 100,
    kap_checked: true,
    inflation_yoy: 0.33,
    counts: { gate_passed: 40, technical_passed: 10, vetoed: 1, candidates: 0 },
    memos: { done: 0, total: 0 },
    candidates: [],
    nearest: [],
    universe: [],
    ...overrides,
  };
}

describe('levelMarks', () => {
  it('puts the stop at the left edge and the furthest target at the right', () => {
    const marks = levelMarks(levels());
    expect(marks).not.toBeNull();
    expect(marks!.stop).toBe(0);
    expect(marks!.target2).toBe(1);
    expect(marks!.entryLow).toBeLessThan(marks!.price);
    expect(marks!.price).toBeLessThan(marks!.target1);
  });

  it('uses target1 as the right edge when there is no second target', () => {
    expect(levelMarks(levels({ target2: null }))!.target1).toBe(1);
  });

  it('refuses a range that does not span — a stop above the target is not a bar', () => {
    expect(levelMarks(levels({ stop: 120 }))).toBeNull();
  });
});

describe('formatting', () => {
  it('formats reward to risk with one decimal and a dash for nothing', () => {
    expect(formatRr(2.41)).toBe('2.4×');
    expect(formatRr(null)).toBe('—');
    expect(formatRr(Number.NaN)).toBe('—');
  });

  it('tones a score, and leaves a missing one subtle rather than red', () => {
    expect(scoreTone(80)).toBe('text-up');
    expect(scoreTone(40)).toBe('text-fg-muted');
    expect(scoreTone(null)).toBe('text-fg-subtle');
  });

  it('measures a distance only against a real price', () => {
    expect(distanceTo(110, 100)).toBeCloseTo(0.1);
    expect(distanceTo(110, null)).toBeNull();
    expect(distanceTo(110, 0)).toBeNull();
  });
});

describe('rejectionText', () => {
  it('names the first veto over the generic label', () => {
    const vetoed = row({
      vetoes: [{ key: 'losses_3_of_4', label: "Son 4 çeyreğin 3'ü zarar" }],
      rejected_label: 'Temel veto',
    });
    expect(rejectionText(vetoed)).toBe("Son 4 çeyreğin 3'ü zarar");
  });

  it('falls back to the label, then the key, then a dash', () => {
    expect(rejectionText(row())).toBe('Toplam puan 60 altında');
    expect(rejectionText(row({ rejected_label: null, rejected_reason: 'x' }))).toBe('x');
    expect(rejectionText(row({ rejected_label: null, rejected_reason: null }))).toBe('—');
    expect(rejectionText(row({ stage_reached: 'candidate' }))).toBe('Aday');
  });
});

describe('result sentences', () => {
  it('says that no setup is a result', () => {
    expect(summaryLine(result())).toBe('100 hisse tarandı, bugün kurulum yok.');
  });

  it('reports the depth honestly', () => {
    expect(depthNote(result())).toBeNull();
    expect(depthNote(result({ fundamental_depth: 'partial', fundamentals_covered: 80 }))).toContain(
      '80/100'
    );
    expect(depthNote(result({ fundamental_depth: 'ratios_only' }))).toContain('doğrulanmadı');
  });

  it('knows when memos are still arriving', () => {
    expect(memosPending(result({ memos: { done: 2, total: 5 } }))).toBe(true);
    expect(memosPending(result({ memos: { done: 5, total: 5 } }))).toBe(false);
    expect(memosPending(undefined)).toBe(false);
  });
});

function voice(overrides: Partial<RadarVoice> = {}): RadarVoice {
  return {
    voice_id: 'a',
    voice_name: 'Ali',
    stance: 'bullish',
    said_at: '2026-08-20',
    horizon_days: 21,
    target: null,
    quote: '',
    video_title: 't',
    url: 'u',
    outcome: null,
    accuracy: null,
    ...overrides,
  };
}

describe('voices', () => {
  it('labels an ungraded speaker honestly', () => {
    expect(voiceLabel(voice())).toBe('Ali · Yükseliş · henüz notlanmadı');
  });

  it('shows the shrunk accuracy and flags a short record', () => {
    const acc = { hits: 1, misses: 0, flats: 0, pending: 0, n: 1, raw: 1, shrunk: 0.6 };
    expect(voiceLabel(voice({ accuracy: acc, stance: 'bearish' }))).toBe(
      'Ali · Düşüş · isabet %60 (n=1, erken)'
    );
    const long = { ...acc, hits: 9, misses: 3, n: 12, raw: 0.75, shrunk: 0.6875 };
    expect(voiceLabel(voice({ accuracy: long }))).toBe('Ali · Yükseliş · isabet %69 (n=12)');
  });

  it('tones by stance', () => {
    expect(stanceTone('bullish')).toBe('up');
    expect(stanceTone('bearish')).toBe('down');
    expect(stanceTone('neutral')).toBe('neutral');
  });

  it('reports a skipped or partial commentator step', () => {
    expect(voicesNote(result())).toBeNull();
    const report = {
      checked: true,
      voices: 3,
      videos: 5,
      transcripts: 5,
      extractions: 0,
      graded: 0,
      failures: [],
    };
    expect(voicesNote(result({ voices_report: report }))).toBeNull();
    expect(voicesNote(result({ voices_report: { ...report, checked: false } }))).toContain(
      'yapılamadı'
    );
    expect(voicesNote(result({ voices_report: { ...report, failures: ['x'] } }))).toContain('1');
  });
});
