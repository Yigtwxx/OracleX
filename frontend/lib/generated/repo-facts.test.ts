import { describe, expect, it } from 'vitest';
import { API, HEALTH, LLM, MCP, SKILLS, TESTS, VERSION } from './repo-facts';

/**
 * The generated module is checked against its sources in CI, so these tests are
 * not about whether the numbers are current. They are about whether the numbers
 * are *coherent* — a generator that silently emitted a partial method table or
 * dropped a tool group would still produce a file that matched itself.
 */

describe('VERSION', () => {
  it('is a semver triple', () => {
    expect(VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it('is what every skill declares — one version for the repository', () => {
    for (const skill of SKILLS) expect(skill.version).toBe(VERSION);
  });
});

describe('API', () => {
  it('accounts for every operation in the method breakdown', () => {
    const summed = API.methods.reduce((total, row) => total + row.count, 0);
    expect(summed).toBe(API.operations);
  });

  it('cannot require auth on more operations than it has', () => {
    expect(API.authRequired).toBeLessThanOrEqual(API.operations);
    expect(API.authRequired).toBeGreaterThan(0);
  });

  it('has at most one operation per path per method', () => {
    expect(API.paths).toBeLessThanOrEqual(API.operations);
  });

  it('lists the socket routes the schema omits', () => {
    expect(API.websockets.length).toBeGreaterThan(0);
    for (const route of API.websockets) expect(route).toMatch(/^\//);
  });

  it('names each method once', () => {
    const methods = API.methods.map((row) => row.method);
    expect(new Set(methods).size).toBe(methods.length);
  });
});

describe('MCP', () => {
  it('has every tool in exactly one group', () => {
    const flat = MCP.groups.flatMap((group) => group.tools);
    expect(flat.length).toBe(MCP.total);
    expect(new Set(flat).size).toBe(flat.length);
  });

  it('has no empty group', () => {
    for (const group of MCP.groups) expect(group.tools.length).toBeGreaterThan(0);
  });

  it('names tools the way a tool call has to spell them', () => {
    for (const tool of MCP.groups.flatMap((group) => group.tools)) {
      expect(tool).toMatch(/^[a-z][a-z0-9_]*$/);
    }
  });
});

describe('SKILLS', () => {
  it('gives a generated half to the two market skills and not to the dev one', () => {
    const generated = SKILLS.filter((skill) => skill.generated !== null);
    expect(generated.map((skill) => skill.name)).toEqual(['oracle-x-api', 'oracle-x-bist']);
  });

  it('does not claim to document more operations than exist', () => {
    const halves = SKILLS.map((skill) => skill.generated).filter(
      (generated) => generated !== null,
    );
    expect(halves.length).toBeGreaterThan(0);
    for (const generated of halves) {
      expect(generated!.endpoints).toBeLessThanOrEqual(API.operations);
      expect(generated!.groups).toBeGreaterThan(0);
    }
  });

  // The allowlist is partitioned between the skills, not copied into both. If a
  // group is ever assigned to two of them the sum silently doubles, and this is
  // the only place that would notice.
  it('partitions the allowlist rather than duplicating it', () => {
    const total = SKILLS.reduce((sum, skill) => sum + (skill.generated?.endpoints ?? 0), 0);
    expect(total).toBeLessThanOrEqual(API.operations);
  });
});

describe('HEALTH', () => {
  it('has one row per category', () => {
    expect(HEALTH.rows).toHaveLength(HEALTH.categories);
  });

  it('agrees with itself about how many categories are critical', () => {
    expect(HEALTH.rows.filter((row) => row.critical)).toHaveLength(HEALTH.critical);
  });

  it('counts distinct upstreams, so the total cannot exceed the sum of the rows', () => {
    const summed = HEALTH.rows.reduce((total, row) => total + row.upstreams, 0);
    expect(HEALTH.upstreams).toBeLessThanOrEqual(summed);
  });

  it('gives every category at least one upstream to report on', () => {
    for (const row of HEALTH.rows) expect(row.upstreams).toBeGreaterThan(0);
  });
});

describe('LLM', () => {
  it('has at least one adapter per shape it can speak', () => {
    expect(LLM.adapters.length).toBeGreaterThan(0);
    expect(new Set(LLM.adapters).size).toBe(LLM.adapters.length);
  });

  it('has more presets than adapters — presets are rows, adapters are code', () => {
    expect(LLM.presets).toBeGreaterThan(LLM.adapters.length);
  });
});

describe('TESTS', () => {
  it('totals its suites', () => {
    const summed = TESTS.suites.reduce((total, suite) => total + suite.tests, 0);
    expect(summed).toBe(TESTS.total);
  });

  it('never reports fewer tests than files, which would mean an empty file', () => {
    for (const suite of TESTS.suites) {
      expect(suite.files).toBeGreaterThan(0);
      expect(suite.tests).toBeGreaterThanOrEqual(suite.files);
    }
  });
});
