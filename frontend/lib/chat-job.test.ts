import { describe, it, expect } from 'vitest';
import { toChatJob, toChatStep, isSettled, toStepRow, toStoredSteps } from './chat-job';

describe('toChatStep', () => {
  it('maps snake_case to camelCase', () => {
    const step = toChatStep(
      {
        id: '2',
        tool: 'web_search',
        label: 'Searching the web',
        status: 'done',
        detail: '5 results',
        duration_seconds: 1.6,
      },
      0
    );

    expect(step).toEqual({
      id: '2',
      tool: 'web_search',
      label: 'Searching the web',
      status: 'done',
      detail: '5 results',
      durationSeconds: 1.6,
    });
  });

  it('turns the backend null into undefined', () => {
    const step = toChatStep(
      { id: '0', tool: 'x', label: 'x', status: 'running', detail: null, duration_seconds: null },
      0
    );

    expect(step.detail).toBeUndefined();
    expect(step.durationSeconds).toBeUndefined();
  });

  it('treats an unknown status as still running', () => {
    // A status the frontend does not know must not render as an unstyled row.
    // Running is the state that resolves itself on the next poll.
    const step = toChatStep({ id: '0', tool: 'x', label: 'x', status: 'reticulating' }, 0);

    expect(step.status).toBe('running');
  });

  it('falls back to the index and the tool name when fields are missing', () => {
    const step = toChatStep({ tool: 'read_page' }, 3);

    expect(step.id).toBe('3');
    expect(step.label).toBe('read_page');
  });
});

describe('toChatJob', () => {
  it('maps a running job with steps', () => {
    const job = toChatJob({
      job_id: 'abc',
      status: 'running',
      steps: [{ id: '0', tool: 'market_snapshot', label: 'Reading', status: 'running' }],
      elapsed_seconds: 4.2,
      result: null,
      error: null,
    });

    expect(job.jobId).toBe('abc');
    expect(job.status).toBe('running');
    expect(job.steps).toHaveLength(1);
    expect(job.elapsedSeconds).toBe(4.2);
    expect(job.result).toBeUndefined();
    expect(job.error).toBeUndefined();
  });

  it('maps the finished result', () => {
    const job = toChatJob({
      job_id: 'abc',
      status: 'done',
      steps: [],
      elapsed_seconds: 42,
      result: {
        response: 'BTC is at 60k',
        thinking_time: 41.8,
        sources: ['Market snapshot', 'Web search'],
        detected_symbol: 'BTC',
        session_title: 'BTC check',
      },
    });

    expect(job.result).toEqual({
      response: 'BTC is at 60k',
      thinkingTime: 41.8,
      sources: ['Market snapshot', 'Web search'],
      detectedSymbol: 'BTC',
      sessionTitle: 'BTC check',
    });
  });

  it('survives a result missing its optional fields', () => {
    const job = toChatJob({
      job_id: 'abc',
      status: 'done',
      result: { response: 'hi', thinking_time: 1 },
    });

    expect(job.result?.sources).toEqual([]);
    expect(job.result?.sessionTitle).toBeUndefined();
  });

  it('defaults a missing steps array rather than throwing', () => {
    const job = toChatJob({ job_id: 'abc', status: 'queued' });

    expect(job.steps).toEqual([]);
    expect(job.elapsedSeconds).toBe(0);
  });

  it('carries the error through', () => {
    const job = toChatJob({ job_id: 'abc', status: 'error', error: 'provider timed out' });

    expect(job.status).toBe('error');
    expect(job.error).toBe('provider timed out');
  });
});

describe('persistence round trip', () => {
  it('survives a trip through the stored shape', () => {
    const step = toChatStep(
      {
        id: '1',
        tool: 'web_search',
        label: 'Searching',
        status: 'done',
        detail: '5 results',
        duration_seconds: 2.4,
      },
      0
    );

    expect(toStoredSteps([toStepRow(step)])).toEqual([step]);
  });

  it('writes undefined back as null, which is what the column holds', () => {
    const step = toChatStep({ id: '0', tool: 't', label: 'l', status: 'empty' }, 0);

    expect(toStepRow(step)).toMatchObject({ detail: null, duration_seconds: null });
  });

  it('treats a message with no stored steps as having no timeline', () => {
    // Both a user message and any turn written before migration 009.
    expect(toStoredSteps(null)).toBeUndefined();
    expect(toStoredSteps(undefined)).toBeUndefined();
    expect(toStoredSteps([])).toBeUndefined();
  });
});

describe('isSettled', () => {
  it('is true only once the job stops moving', () => {
    expect(isSettled(undefined)).toBe(false);
    expect(isSettled(toChatJob({ status: 'queued' }))).toBe(false);
    expect(isSettled(toChatJob({ status: 'running' }))).toBe(false);
    expect(isSettled(toChatJob({ status: 'done' }))).toBe(true);
    expect(isSettled(toChatJob({ status: 'error' }))).toBe(true);
  });
});
