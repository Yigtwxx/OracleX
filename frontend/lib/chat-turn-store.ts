/**
 * The chat turn in flight, held outside React.
 *
 * The backend already runs a turn as a job, so the answer survives a client
 * that stops watching. What did not survive was the *client*: the job id lived
 * in `OracleChatPage`'s state, so leaving `/chat` for another page unmounted
 * the poller, and nothing ever collected the answer or wrote it to history —
 * the turn finished on the server and the reader came back to a conversation
 * that had silently lost a reply. React Query's poll had the same hole in the
 * other direction: `refetchInterval` is suspended while the document is hidden,
 * so switching Chrome tabs froze the turn until the tab was focused again.
 *
 * This module owns both. It is a plain singleton with its own timer, so the
 * poll keeps running across route changes and while the tab is in the
 * background, and it writes the finished answer to the signed-in reader's
 * history itself rather than leaving that to whichever component happens to be
 * mounted when the job settles.
 */

import {
  ApiError,
  cancelChatJob,
  fetchChatJob,
  saveChatMessage as saveChatMessageApi,
} from './api';
import { isSettled, toStepRow, type ChatJob, type ChatStep, type Citation } from './chat-job';

export type ResponseStyle = 'concise' | 'detailed';

/**
 * A message as the page renders it.
 *
 * Defined here rather than in the component because the transcript cache below
 * outlives every mount of that component, so this module is what actually owns
 * the shape.
 */
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  thinkingTime?: number;
  timestamp: Date;
  /**
   * The mode this message was exchanged under, frozen at creation so the
   * entrance animation cannot be replayed by later mode switches. Undefined for
   * messages restored from history: the backend does not persist the mode, and
   * a restored transcript should not animate itself in.
   */
  mode?: ResponseStyle;
  /** What the turn actually did to produce this answer. */
  steps?: ChatStep[];
  /** The pages behind the answer. */
  citations?: Citation[];
  /** The asset this turn resolved to, and whether it was carried over. */
  focusSymbol?: string;
  focusInherited?: boolean;
}

export interface PendingTurn {
  jobId: string;
  /** Null for a signed-out reader, who has no session to persist into. */
  sessionId: string | null;
  style: ResponseStyle;
  /** Whether the answer should be written to the reader's chat history. */
  persist: boolean;
  startedAt: number;
}

export interface SettledTurn {
  jobId: string;
  sessionId: string | null;
  style: ResponseStyle;
  job: ChatJob;
  /**
   * Whether a page was mounted when this landed.
   *
   * Decides who renders it. A turn that settled while someone was watching is
   * appended to the transcript on screen; one that settled while the reader was
   * elsewhere was already written to history by {@link settle}, so appending it
   * on the way back would show the answer twice — once from the reload, once
   * from here.
   */
  observed: boolean;
  /** Whether the answer reached the database. */
  persisted: boolean;
  settledAt: number;
}

export interface ChatTurnSnapshot {
  pending: PendingTurn | null;
  /** The latest poll of the pending turn — its steps are the pending bubble. */
  job: ChatJob | null;
  /** A finished turn no page has rendered yet. */
  settled: SettledTurn | null;
}

/**
 * Matches the old React Query interval, and for the same reason: a turn's steps
 * are the product while it runs, and the payload is a few hundred bytes until
 * the answer lands.
 */
const POLL_INTERVAL_MS = 900;

/**
 * How long after a reload a recorded turn is still worth resuming.
 *
 * `TURN_TIMEOUT` bounds a turn at 400s and `analysis_jobs.RETENTION_BY_KIND`
 * keeps a finished chat job for five minutes, so anything older than about
 * twelve minutes is guaranteed to be gone from the server. Fifteen leaves room
 * for a slow clock without polling for an id that cannot exist.
 */
const RESUME_WINDOW_MS = 15 * 60 * 1000;

/**
 * A settled turn nobody collected goes stale at the same bound. Only the
 * signed-out case can linger — a persisted answer is skipped on return — and
 * appending an hour-old reply to a conversation that has moved on is worse than
 * dropping it.
 */
export const SETTLED_MAX_AGE_MS = RESUME_WINDOW_MS;

/**
 * A dropped poll is not a dead turn — a proxy hiccup must not throw away an
 * answer that is still being written — but it cannot retry forever either, or a
 * backend that has gone away leaves a spinner on screen for good.
 */
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

const STORAGE_KEY = 'oraclex.chat.turn';

const EMPTY: ChatTurnSnapshot = { pending: null, job: null, settled: null };

let state: ChatTurnSnapshot = EMPTY;
const listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout> | null = null;
let consecutiveFailures = 0;
let hydrated = false;
let visibilityBound = false;
/**
 * The history write for the turn that just settled.
 *
 * Held so a page that mounts mid-write can wait for it. Without that, a reader
 * who comes back seconds after the answer landed reloads the conversation from
 * a table the answer has not reached yet, and sees the reply nowhere: not
 * appended here (it was persisted, so appending would double it) and not in the
 * history either.
 */
let persistTask: { jobId: string; done: Promise<void> } | null = null;

function emit(): void {
  for (const listener of listeners) listener();
}

function setState(patch: Partial<ChatTurnSnapshot>): void {
  state = { ...state, ...patch };
  emit();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSnapshot(): ChatTurnSnapshot {
  return state;
}

/** Server render has no turn in flight, and must not read `localStorage`. */
export function getServerSnapshot(): ChatTurnSnapshot {
  return EMPTY;
}

// ─────────────────────────────────────────────────────────────────────────────
// The poll
// ─────────────────────────────────────────────────────────────────────────────

function schedule(delay: number = POLL_INTERVAL_MS): void {
  if (timer) clearTimeout(timer);
  // A chained timeout rather than an interval: a poll that takes longer than
  // the interval would otherwise stack requests on a backend that is already
  // slow, which is exactly when it can least afford them.
  timer = setTimeout(() => {
    void poll();
  }, delay);
}

function stopPolling(): void {
  if (timer) clearTimeout(timer);
  timer = null;
}

async function poll(): Promise<void> {
  timer = null;
  const pending = state.pending;
  if (!pending) return;

  let job: ChatJob;
  try {
    job = await fetchChatJob(pending.jobId);
    consecutiveFailures = 0;
  } catch (error) {
    // A job the server no longer knows about is gone for good: it expired, or
    // it was cancelled from somewhere else. Retrying only delays the report.
    if (error instanceof ApiError && error.status === 404) {
      void settle(
        pending,
        failedJob(pending.jobId, 'This turn expired before its answer arrived.')
      );
      return;
    }
    consecutiveFailures += 1;
    if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
      void settle(pending, failedJob(pending.jobId, 'Oracle stopped responding while answering.'));
      return;
    }
    schedule(POLL_INTERVAL_MS * 2);
    return;
  }

  // The turn may have been cancelled or replaced while this poll was in the
  // air; publishing its steps now would revive a bubble the user dismissed.
  if (state.pending?.jobId !== pending.jobId) return;

  if (isSettled(job)) {
    void settle(pending, job);
    return;
  }
  setState({ job });
  schedule();
}

function failedJob(jobId: string, message: string): ChatJob {
  return {
    jobId,
    status: 'error',
    // Whatever the last poll saw is still the truest account of what the turn
    // managed to do before it was lost.
    steps: state.job?.steps ?? [],
    elapsedSeconds: state.job?.elapsedSeconds ?? 0,
    error: message,
  };
}

/**
 * Retire the pending turn and, when it produced an answer, write it down.
 *
 * The write happens here rather than in the page because that is the whole
 * point of this module: the turn finishes whether or not anything is mounted to
 * watch it, so a reader who navigated away mid-answer finds the reply in the
 * session's history instead of finding it gone.
 */
async function settle(pending: PendingTurn, job: ChatJob): Promise<void> {
  stopPolling();
  clearStoredTurn();

  const observed = listeners.size > 0;
  const answer = job.status === 'done' ? job.result : undefined;
  const shouldPersist = pending.persist && !!answer;

  setState({
    pending: null,
    job: null,
    settled: {
      jobId: pending.jobId,
      sessionId: pending.sessionId,
      style: pending.style,
      job,
      observed,
      persisted: shouldPersist,
      settledAt: Date.now(),
    },
  });

  if (!shouldPersist || !answer) {
    persistTask = null;
    return;
  }

  const done = (async () => {
    try {
      await saveChatMessageApi({
        role: 'assistant',
        content: answer.response,
        session_id: pending.sessionId ?? undefined,
        thinking_time: answer.thinkingTime,
        steps: job.steps.map(toStepRow),
      });
    } catch (error) {
      console.error('Failed to save chat message:', error);
      // The answer is still in `settled`, so a mounted page renders it either
      // way. Reporting the miss matters because the next reload will not have
      // it, and the page decides what to render on this flag.
      if (state.settled?.jobId === pending.jobId) {
        setState({ settled: { ...state.settled, persisted: false } });
      }
    }
  })();

  persistTask = { jobId: pending.jobId, done };
  await done;
}

/**
 * Resolves once the answer for `jobId` has reached the database.
 *
 * Resolves immediately for a turn that was never going to be written down, so a
 * caller can await it unconditionally.
 */
export function whenPersisted(jobId: string): Promise<void> {
  return persistTask?.jobId === jobId ? persistTask.done : Promise.resolve();
}

// ─────────────────────────────────────────────────────────────────────────────
// Reload survival
// ─────────────────────────────────────────────────────────────────────────────

function storeTurn(turn: PendingTurn): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(turn));
  } catch {
    // Private mode, or a full quota. The turn still completes for as long as
    // this document lives; only reload survival is lost.
  }
}

function clearStoredTurn(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // See `storeTurn`.
  }
}

function readStoredTurn(): PendingTurn | null {
  if (typeof window === 'undefined') return null;
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as Partial<PendingTurn>;
    if (typeof parsed.jobId !== 'string' || !parsed.jobId) return null;
    if (typeof parsed.startedAt !== 'number') return null;
    if (Date.now() - parsed.startedAt > RESUME_WINDOW_MS) return null;
    return {
      jobId: parsed.jobId,
      sessionId: typeof parsed.sessionId === 'string' ? parsed.sessionId : null,
      style: parsed.style === 'concise' ? 'concise' : 'detailed',
      persist: parsed.persist === true,
      startedAt: parsed.startedAt,
    };
  } catch {
    return null;
  }
}

/**
 * A hidden tab's timers are throttled to about one wake a minute, which is fine
 * for finishing the turn and useless for showing it. Polling the moment the tab
 * comes back closes the gap between the answer existing and the reader seeing
 * it.
 */
function bindVisibility(): void {
  if (visibilityBound || typeof document === 'undefined') return;
  visibilityBound = true;
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.pending) schedule(0);
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Take ownership of a job the caller has already started.
 *
 * Starting the job stays with the page, because the session row and the user
 * message have to be written first and only the page knows the transcript the
 * turn travels with. Everything after the id exists belongs here.
 */
export function attach(turn: Omit<PendingTurn, 'startedAt'> & { startedAt?: number }): void {
  const pending: PendingTurn = { ...turn, startedAt: turn.startedAt ?? Date.now() };
  consecutiveFailures = 0;
  bindVisibility();
  storeTurn(pending);
  // A previous answer is not the new turn's business; dropping it here also
  // means a settled turn nobody collected cannot resurface later.
  setState({ pending, job: null, settled: null });
  schedule(0);
}

/**
 * Resume a turn recorded before a reload.
 *
 * Idempotent, and safe to call from every mount: it does nothing once a turn is
 * being tracked, so returning to `/chat` mid-answer re-reads the store rather
 * than restarting anything.
 */
export function hydrate(): void {
  if (hydrated) return;
  hydrated = true;
  if (state.pending) return;

  const stored = readStoredTurn();
  if (!stored) {
    clearStoredTurn();
    return;
  }
  consecutiveFailures = 0;
  bindVisibility();
  setState({ pending: stored, job: null, settled: null });
  schedule(0);
}

/**
 * Stop the turn that is running.
 *
 * Local state goes first and the request after, because the point of pressing
 * stop is that the composer comes back immediately. The server call still
 * matters: it frees the LLM and the upstream feeds rather than leaving them
 * working on an answer nobody will read.
 */
export function cancel(): void {
  const pending = state.pending;
  if (!pending) return;

  stopPolling();
  clearStoredTurn();
  setState({ pending: null, job: null, settled: null });

  void cancelChatJob(pending.jobId).catch(() => {
    // Already gone from this client's point of view. A failed cancel means the
    // server works for a few more seconds and then throws the answer away.
  });
}

/** Drop a settled turn once a page has rendered it. */
export function consume(jobId: string): void {
  if (state.settled?.jobId !== jobId) return;
  setState({ settled: null });
}

// ─────────────────────────────────────────────────────────────────────────────
// Transcript cache
// ─────────────────────────────────────────────────────────────────────────────

export interface CachedTranscript {
  sessionId: string | null;
  messages: ChatMessage[];
  followups: string[];
  /** The mode the composer was in — part of where the reader left off. */
  style: ResponseStyle;
}

/**
 * The conversation on screen, kept across mounts.
 *
 * A signed-in reader's transcript comes back from the database, but only after
 * a round trip and only for a session that exists — a signed-out reader has
 * neither, so leaving `/chat` used to wipe the conversation outright. In memory
 * on purpose: this is about surviving a route change, and a transcript written
 * to storage would outlive the sign-out that should have ended it.
 */
let transcript: CachedTranscript | null = null;

export function rememberTranscript(next: CachedTranscript): void {
  transcript = next;
}

export function recallTranscript(): CachedTranscript | null {
  return transcript;
}

export function forgetTranscript(): void {
  transcript = null;
}

/** Test seam: drops every trace of a turn, including the stored one. */
export function reset(): void {
  stopPolling();
  clearStoredTurn();
  listeners.clear();
  state = EMPTY;
  transcript = null;
  persistTask = null;
  hydrated = false;
  consecutiveFailures = 0;
}
