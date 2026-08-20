/**
 * The note envelope's branching.
 *
 * Small surface, but two of these guard real failure modes: a note that renders
 * as blank space, and a client that polls a dead provider chain forever.
 */

import { describe, expect, it } from 'vitest';

import {
  aiNotePollInterval,
  aiNoteText,
  isGenerating,
  NOTE_POLL_INTERVAL_MS,
  type AiNote,
} from '@/lib/ai-note';

const note = (over: Partial<AiNote> = {}): AiNote => ({
  status: 'ready',
  note: 'The dollar fell and breadth held.',
  generated_at: '2026-08-18T09:00:00+00:00',
  reason: null,
  ...over,
});

describe('aiNoteText', () => {
  it('returns the prose when one arrived', () => {
    expect(aiNoteText(note())).toBe('The dollar fell and breadth held.');
  });

  it('treats a ready-but-empty note as no note', () => {
    // Otherwise the page renders a paragraph of blank space, which reads as a
    // layout bug rather than as an absent note.
    expect(aiNoteText(note({ note: '   ' }))).toBeNull();
    expect(aiNoteText(note({ note: null }))).toBeNull();
  });

  it('renders nothing while one is being written', () => {
    expect(aiNoteText(note({ status: 'generating', note: null }))).toBeNull();
  });

  it('survives a payload that has no note at all', () => {
    expect(aiNoteText(undefined)).toBeNull();
    expect(aiNoteText(null)).toBeNull();
  });
});

describe('aiNotePollInterval', () => {
  it('polls only while a run is in flight', () => {
    expect(aiNotePollInterval(note({ status: 'generating' }))).toBe(NOTE_POLL_INTERVAL_MS);
  });

  it('stops once the note arrives', () => {
    expect(aiNotePollInterval(note())).toBe(false);
  });

  it('stops when there will never be a note', () => {
    // The regression: an unavailable note means the provider chain is down or
    // there was nothing to say. Polling it would re-ask, every few seconds, for
    // as long as the tab stayed open.
    expect(aiNotePollInterval(note({ status: 'unavailable', reason: 'ai_disabled' }))).toBe(false);
    expect(aiNotePollInterval(undefined)).toBe(false);
  });
});

describe('isGenerating', () => {
  it('is true only for a run in flight', () => {
    expect(isGenerating(note({ status: 'generating' }))).toBe(true);
    expect(isGenerating(note())).toBe(false);
    expect(isGenerating(note({ status: 'unavailable' }))).toBe(false);
  });
});
