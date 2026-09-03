import { describe, expect, it } from 'vitest';
import { CHAIN_BOXES, CHAIN_FLOWS, CHAIN_STAMPS, CHAIN_VIEW, phasesAt } from './chain';

const KEYS = [
  'request',
  'prefer',
  'toLocal',
  'local',
  'toHosted',
  'hosted',
  'toAnswered',
  'answered',
  'toReply',
  'reply',
] as const;

describe('phasesAt', () => {
  it('starts with nothing drawn', () => {
    const phases = phasesAt(0);
    for (const key of KEYS) expect(phases[key]).toBe(0);
  });

  it('finishes every phase by the end', () => {
    const phases = phasesAt(1);
    for (const key of KEYS) expect(phases[key]).toBe(1);
  });

  it('never goes backwards', () => {
    let previous = phasesAt(0);
    for (let step = 1; step <= 100; step += 1) {
      const current = phasesAt(step / 100);
      for (const key of KEYS) {
        expect(current[key], `${key} went backwards at ${step}`).toBeGreaterThanOrEqual(
          previous[key]
        );
      }
      previous = current;
    }
  });

  it('opens the phases in the order the request travels', () => {
    // Sampled mid-run: at any point, an earlier step is at least as far along as
    // a later one. That is what makes the diagram read as a descent rather than
    // as six things fading in together.
    for (let step = 0; step <= 100; step += 5) {
      const phases = phasesAt(step / 100);
      for (let i = 1; i < KEYS.length; i += 1) {
        expect(phases[KEYS[i - 1]]).toBeGreaterThanOrEqual(phases[KEYS[i]]);
      }
    }
  });
});

describe('CHAIN geometry', () => {
  it('keeps every box inside the design space', () => {
    for (const box of CHAIN_BOXES) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(CHAIN_VIEW.width);
      expect(box.y + box.height).toBeLessThanOrEqual(CHAIN_VIEW.height);
    }
  });

  it('keeps every cooldown stamp inside the design space', () => {
    for (const stamp of CHAIN_STAMPS) {
      expect(stamp.x + stamp.width).toBeLessThanOrEqual(CHAIN_VIEW.width);
      expect(stamp.y + stamp.height).toBeLessThanOrEqual(CHAIN_VIEW.height);
    }
  });

  it('hangs every stamp off a box that exists', () => {
    const keys = new Set(CHAIN_BOXES.map((box) => box.key));
    for (const stamp of CHAIN_STAMPS) expect(keys.has(stamp.forKey)).toBe(true);
  });

  it('only stamps a cooldown on a rung that declined', () => {
    for (const stamp of CHAIN_STAMPS) {
      const box = CHAIN_BOXES.find((candidate) => candidate.key === stamp.forKey);
      expect(box?.outcome).toBe('declined');
    }
  });

  it('has one flow segment per gap between the rungs', () => {
    expect(CHAIN_FLOWS).toHaveLength(CHAIN_BOXES.filter((box) => !box.optional).length - 1);
    for (const flow of CHAIN_FLOWS) expect(flow).toHaveLength(2);
  });

  it('only ever descends', () => {
    for (const [from, to] of CHAIN_FLOWS) expect(to.y).toBeGreaterThan(from.y);
  });

  it('names every box once', () => {
    const keys = CHAIN_BOXES.map((box) => box.key);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
