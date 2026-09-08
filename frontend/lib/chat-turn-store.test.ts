import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { ApiError } from './api';
import type { ChatJob } from './chat-job';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ApiError: actual.ApiError,
    fetchChatJob: vi.fn(),
    cancelChatJob: vi.fn(async () => ({}) as never),
    saveChatMessage: vi.fn(async () => ({ success: true })),
  };
});

const api = await import('./api');
const store = await import('./chat-turn-store');

const fetchChatJob = vi.mocked(api.fetchChatJob);
const cancelChatJob = vi.mocked(api.cancelChatJob);
const saveChatMessage = vi.mocked(api.saveChatMessage);

function job(status: ChatJob['status'], extra: Partial<ChatJob> = {}): ChatJob {
  return { jobId: 'j1', status, steps: [], elapsedSeconds: 1, ...extra };
}

const ANSWER = {
  response: 'Bitcoin is holding 60k.',
  thinkingTime: 12,
  sources: [],
  citations: [],
  followups: [],
};

/** Runs the poll loop far enough to settle, flushing the awaits inside it. */
async function drain(ms = 5000) {
  await vi.advanceTimersByTimeAsync(ms);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  store.reset();
});

afterEach(() => {
  store.reset();
  vi.useRealTimers();
});

describe('attach', () => {
  it('polls until the turn settles and hands the answer over', async () => {
    fetchChatJob
      .mockResolvedValueOnce(job('running', { steps: [] }))
      .mockResolvedValueOnce(job('done', { result: ANSWER }));

    const seen: string[] = [];
    store.subscribe(() => seen.push(store.getSnapshot().pending ? 'pending' : 'idle'));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();

    const settled = store.getSnapshot().settled;
    expect(settled?.job.result?.response).toBe('Bitcoin is holding 60k.');
    expect(store.getSnapshot().pending).toBeNull();
    expect(seen).toContain('pending');
  });

  it('writes the answer to history itself, so an unwatched turn is not lost', async () => {
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'concise', persist: true });
    await drain();

    expect(saveChatMessage).toHaveBeenCalledWith(
      expect.objectContaining({ role: 'assistant', content: ANSWER.response, session_id: 's1' })
    );
    expect(store.getSnapshot().settled?.persisted).toBe(true);
  });

  it('leaves a signed-out reader’s answer unpersisted', async () => {
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: null, style: 'concise', persist: false });
    await drain();

    expect(saveChatMessage).not.toHaveBeenCalled();
    expect(store.getSnapshot().settled?.persisted).toBe(false);
  });

  it('records whether anything was mounted to see the answer', async () => {
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();
    expect(store.getSnapshot().settled?.observed).toBe(false);

    store.reset();
    fetchChatJob.mockResolvedValue(job('done', { jobId: 'j2', result: ANSWER }));
    store.subscribe(() => {});
    store.attach({ jobId: 'j2', sessionId: 's1', style: 'detailed', persist: true });
    await drain();
    expect(store.getSnapshot().settled?.observed).toBe(true);
  });
});

describe('poll failures', () => {
  it('settles as an error when the job is gone', async () => {
    fetchChatJob.mockRejectedValue(new ApiError(404, 'Chat job not found'));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();

    expect(store.getSnapshot().settled?.job.status).toBe('error');
    expect(saveChatMessage).not.toHaveBeenCalled();
  });

  it('rides out a dropped poll rather than throwing the answer away', async () => {
    fetchChatJob
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();

    expect(store.getSnapshot().settled?.job.result?.response).toBe(ANSWER.response);
  });

  it('gives up once the backend has stopped answering entirely', async () => {
    fetchChatJob.mockRejectedValue(new Error('network'));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain(60_000);

    expect(store.getSnapshot().settled?.job.status).toBe('error');
    expect(store.getSnapshot().pending).toBeNull();
  });
});

describe('cancel', () => {
  it('stops the poll and leaves nothing to render', async () => {
    fetchChatJob.mockResolvedValue(job('running'));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain(1000);
    store.cancel();
    const callsAtCancel = fetchChatJob.mock.calls.length;
    await drain(5000);

    expect(cancelChatJob).toHaveBeenCalledWith('j1');
    expect(fetchChatJob.mock.calls.length).toBe(callsAtCancel);
    expect(store.getSnapshot()).toEqual({ pending: null, job: null, settled: null });
  });
});

describe('consume', () => {
  it('drops the settled turn once a page has rendered it', async () => {
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();
    store.consume('j1');

    expect(store.getSnapshot().settled).toBeNull();
  });

  it('ignores an id that is not the settled one', async () => {
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();
    store.consume('other');

    expect(store.getSnapshot().settled).not.toBeNull();
  });
});

describe('the transcript cache', () => {
  it('hands the conversation back to the next mount', () => {
    store.rememberTranscript({
      sessionId: 's1',
      messages: [],
      followups: ['What about ETH?'],
      style: 'concise',
    });
    expect(store.recallTranscript()?.followups).toEqual(['What about ETH?']);

    store.forgetTranscript();
    expect(store.recallTranscript()).toBeNull();
  });
});

describe('reload survival', () => {
  /** The store only ever touches `window.localStorage`, so this is enough. */
  function stubStorage(initial: Record<string, string> = {}) {
    const bag = { ...initial };
    vi.stubGlobal('window', {
      localStorage: {
        getItem: (key: string) => bag[key] ?? null,
        setItem: (key: string, value: string) => {
          bag[key] = value;
        },
        removeItem: (key: string) => {
          delete bag[key];
        },
      },
    });
    return bag;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('records the turn and resumes polling it after a reload', async () => {
    const bag = stubStorage();
    fetchChatJob.mockResolvedValue(job('running'));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'concise', persist: true });
    await drain(1000);
    expect(bag['oraclex.chat.turn']).toContain('j1');

    // The reload: the module's memory is gone, the stored turn is not.
    // Snapshotted first because `reset` is also what clears the record.
    const survived = { ...bag };
    store.reset();
    stubStorage(survived);
    store.hydrate();
    await drain(1000);

    expect(store.getSnapshot().pending?.jobId).toBe('j1');
    expect(store.getSnapshot().pending?.style).toBe('concise');
  });

  it('ignores a turn too old to still exist on the server', async () => {
    stubStorage({
      'oraclex.chat.turn': JSON.stringify({
        jobId: 'j1',
        sessionId: 's1',
        style: 'detailed',
        persist: true,
        startedAt: Date.now() - 60 * 60 * 1000,
      }),
    });

    store.hydrate();
    await drain(1000);

    expect(store.getSnapshot().pending).toBeNull();
    expect(fetchChatJob).not.toHaveBeenCalled();
  });

  it('forgets the stored turn once it settles', async () => {
    const bag = stubStorage();
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();

    expect(bag['oraclex.chat.turn']).toBeUndefined();
  });
});

describe('whenPersisted', () => {
  it('resolves only once the answer has reached the database', async () => {
    let release: (() => void) | undefined;
    saveChatMessage.mockImplementationOnce(
      () => new Promise((resolve) => (release = () => resolve({ success: true })))
    );
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: 's1', style: 'detailed', persist: true });
    await drain();

    let settled = false;
    void store.whenPersisted('j1').then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);

    release?.();
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(true);
  });

  it('resolves immediately for a turn that was never written down', async () => {
    fetchChatJob.mockResolvedValue(job('done', { result: ANSWER }));

    store.attach({ jobId: 'j1', sessionId: null, style: 'detailed', persist: false });
    await drain();

    await expect(store.whenPersisted('j1')).resolves.toBeUndefined();
  });
});
