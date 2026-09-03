import { describe, expect, it } from 'vitest';

import type { AiNote } from '@/lib/ai-note';
import {
  BAND_CHIP,
  BAND_FILL,
  BAND_LEVEL_LABEL,
  BAND_TITLE,
  MAX_SCORE,
  kapNoteMessage,
  kapNoteRetryable,
  scoreFillPct,
} from '@/lib/bist-kap';

function note(overrides: Partial<AiNote> = {}): AiNote {
  return { status: 'ready', note: 'Bir cümle.', generated_at: null, reason: null, ...overrides };
}

describe('kapNoteMessage', () => {
  it('says nothing when there is prose to draw instead', () => {
    expect(kapNoteMessage(note(), false)).toBeNull();
  });

  it('does not draw a blank panel for a ready note with an empty body', () => {
    // `ready` with "" would otherwise fall through to the note component and
    // render as empty space, which reads as a layout bug rather than as a note
    // that never arrived. It claims no cause, because none is known.
    const message = kapNoteMessage(note({ note: '   ' }), false);
    expect(message).toBe('Bu bildirim için analiz üretilemedi.');
    expect(kapNoteRetryable(note({ note: '   ' }), false)).toBe(true);
  });

  it('says the filing is being read while the run is in flight', () => {
    expect(kapNoteMessage(note({ status: 'generating', note: null }), false)).toBe(
      'Bildirim okunuyor…'
    );
    expect(kapNoteMessage(undefined, false)).toBe('Bildirim okunuyor…');
  });

  it('reports a disabled model layer differently from an unreachable one', () => {
    const disabled = kapNoteMessage(
      note({ status: 'unavailable', note: null, reason: 'ai_disabled' }),
      false
    );
    const unreachable = kapNoteMessage(
      note({ status: 'unavailable', note: null, reason: 'provider_unavailable' }),
      false
    );
    expect(disabled).not.toEqual(unreachable);
    expect(disabled).toContain('kapalı');
  });

  it('names a filing whose substance is in an attachment', () => {
    const message = kapNoteMessage(
      note({ status: 'unavailable', note: null, reason: 'insufficient_data' }),
      false
    );
    expect(message).toContain('ekte');
  });

  it('reports a failed request as a request, not as a missing note', () => {
    expect(kapNoteMessage(undefined, true)).toContain('KAP akışından');
  });
});

describe('kapNoteRetryable', () => {
  it('offers a retry for an unreachable provider and a failed request', () => {
    expect(kapNoteRetryable(undefined, true)).toBe(true);
    expect(
      kapNoteRetryable(
        note({ status: 'unavailable', note: null, reason: 'provider_unavailable' }),
        false
      )
    ).toBe(true);
  });

  it('does not offer a retry for a model layer that is switched off', () => {
    expect(
      kapNoteRetryable(note({ status: 'unavailable', note: null, reason: 'ai_disabled' }), false)
    ).toBe(false);
  });

  it('does not offer a retry while the note is still being written', () => {
    expect(kapNoteRetryable(note({ status: 'generating', note: null }), false)).toBe(false);
    expect(kapNoteRetryable(note(), false)).toBe(false);
  });
});

describe('band presentation', () => {
  it('never uses the direction colours for a band', () => {
    // Green and red mean up and down on every other surface of this realm. A
    // capital increase is neither, and painting one red would tell a reader the
    // board made a call it explicitly does not make.
    for (const chip of Object.values(BAND_CHIP)) {
      expect(chip).not.toMatch(/\b(text|bg|border)-(up|down)\b/);
    }
  });

  it('draws an unclassified filing as an absent reading, not a low one', () => {
    expect(BAND_CHIP.unclassified).toContain('border-dashed');
    expect(BAND_CHIP.unclassified).not.toEqual(BAND_CHIP.routine);
  });

  it('leaves the routine band unfilled', () => {
    // Two rows in three on a live tape. A chip on all of them is a chip on none.
    expect(BAND_CHIP.routine).toContain('border-transparent');
    expect(BAND_CHIP.routine).not.toMatch(/bg-/);
  });

  it('says in every tooltip that the band is not a price call', () => {
    expect(BAND_TITLE.high).toContain('Fiyat tahmini değil');
    expect(BAND_TITLE.medium).toContain('Fiyat tahmini değil');
  });
});

describe('the materiality bar', () => {
  it('fills in proportion to the score', () => {
    expect(scoreFillPct(MAX_SCORE)).toBe(100);
    expect(scoreFillPct(5)).toBe(50);
    expect(scoreFillPct(1)).toBe(10);
  });

  it('keeps a higher score visibly ahead of a lower one', () => {
    expect(scoreFillPct(9)).toBeGreaterThan(scoreFillPct(6));
    expect(scoreFillPct(6)).toBeGreaterThan(scoreFillPct(3));
  });

  it('fills nothing at all for an unclassified filing', () => {
    // Any fill would place it on a scale it was never placed on. An empty
    // track is the honest picture of a reading that was not taken.
    expect(scoreFillPct(null)).toBe(0);
    expect(BAND_FILL.unclassified).toBe('');
  });

  it('never overruns the track, whatever the backend sends', () => {
    // The scale is declared in two places — Python and here — so a backend
    // that outgrew this one must clamp rather than paint past the track.
    expect(scoreFillPct(MAX_SCORE + 5)).toBe(100);
    expect(scoreFillPct(-3)).toBe(0);
    expect(scoreFillPct(Number.NaN)).toBe(0);
  });

  it('carries the level in words for a reader who cannot see the bar', () => {
    for (const label of Object.values(BAND_LEVEL_LABEL)) {
      expect(label).toMatch(/^Önem: /);
    }
    expect(BAND_LEVEL_LABEL.unclassified).toContain('belirlenemedi');
  });

  it('keeps the bar off the direction palette, as the chip is', () => {
    for (const fill of Object.values(BAND_FILL)) {
      expect(fill).not.toMatch(/\bbg-(up|down)\b/);
    }
  });
});
