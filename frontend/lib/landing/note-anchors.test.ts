import { describe, expect, it } from 'vitest';
import { NOTE_ANCHORS, anchorOf } from './note-anchors';
import { FEATURES, windowFor } from './stages';

describe('NOTE_ANCHORS', () => {
  it('covers the print band and every feature panel', () => {
    const keys = NOTE_ANCHORS.map((a) => a.key);
    expect(keys).toContain('print');
    for (const feature of FEATURES) {
      expect(keys, `feature ${feature.key} has no anchor`).toContain(feature.key);
    }
  });

  it('draws each wire inside its own stage', () => {
    for (const anchor of NOTE_ANCHORS) {
      const stage = windowFor(anchor.key);
      expect(anchor.from, `anchor ${anchor.key}`).toBeGreaterThanOrEqual(stage.from);
      expect(anchor.to, `anchor ${anchor.key}`).toBeLessThanOrEqual(stage.to);
      expect(anchor.to).toBeGreaterThan(anchor.from);
    }
  });

  it('keeps every pick in range', () => {
    for (const anchor of NOTE_ANCHORS) {
      expect(anchor.pick).toBeGreaterThanOrEqual(0);
      expect(anchor.pick).toBeLessThan(1);
    }
  });

  it('gives the panels different picks rather than one shared bar', () => {
    const picks = new Set(NOTE_ANCHORS.map((a) => a.pick));
    expect(picks.size).toBe(NOTE_ANCHORS.length);
  });

  it('is deterministic — the seed is what keeps server and client in step', () => {
    // A wire that moved between render and hydration is a visible jump, so this
    // is a correctness property, not a tidiness one.
    expect(anchorOf('ai')).toEqual(anchorOf('ai'));
    expect(anchorOf('ai')?.pick).not.toBe(anchorOf('social')?.pick);
  });
});
