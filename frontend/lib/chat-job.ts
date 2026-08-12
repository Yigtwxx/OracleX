/**
 * Wire shapes for a chat turn run as a background job.
 *
 * Kept apart from `lib/api.ts` because it is the one piece of new frontend
 * logic worth testing on its own: the backend speaks snake_case and uses `null`
 * for "not yet", and every field here has a state that only exists while a step
 * is still running.
 */

/**
 * How a step ended.
 *
 * `empty` is not a failure and is not `done` either — the tool ran and found
 * nothing, which the answer should report as a gap. Collapsing the two would
 * lose the distinction the backend went to some trouble to keep.
 */
export type StepStatus = 'pending' | 'running' | 'done' | 'empty' | 'failed' | 'skipped';

export interface ChatStep {
  id: string;
  tool: string;
  label: string;
  status: StepStatus;
  /** One line of what happened — "5 results", "that publisher is not responding". */
  detail?: string;
  /** Absent while the step is still running. */
  durationSeconds?: number;
}

export interface ChatJob {
  jobId: string;
  status: 'queued' | 'running' | 'done' | 'error';
  steps: ChatStep[];
  elapsedSeconds: number;
  result?: ChatJobResult;
  error?: string;
}

export interface ChatJobResult {
  response: string;
  thinkingTime: number;
  sources: string[];
  detectedSymbol?: string;
  sessionTitle?: string;
}

interface RawChatStep {
  id?: string;
  tool?: string;
  label?: string;
  status?: string;
  detail?: string | null;
  duration_seconds?: number | null;
}

interface RawChatJob {
  job_id?: string;
  status?: string;
  steps?: RawChatStep[] | null;
  elapsed_seconds?: number | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

const STEP_STATUSES: StepStatus[] = ['pending', 'running', 'done', 'empty', 'failed', 'skipped'];

const JOB_STATUSES: ChatJob['status'][] = ['queued', 'running', 'done', 'error'];

/** `null` is how the backend spells "not yet"; the UI wants `undefined`. */
function optional<T>(value: T | null | undefined): T | undefined {
  return value === null || value === undefined ? undefined : value;
}

export function toChatStep(raw: RawChatStep, index: number): ChatStep {
  const status = raw.status as StepStatus;
  return {
    id: raw.id ?? String(index),
    tool: raw.tool ?? 'unknown',
    label: raw.label || raw.tool || 'Working',
    // An unrecognised status must not render as an unstyled row: treat anything
    // the frontend does not know about as still in flight, which is the state
    // that resolves itself on the next poll.
    status: STEP_STATUSES.includes(status) ? status : 'running',
    detail: optional(raw.detail),
    durationSeconds: optional(raw.duration_seconds),
  };
}

export function toChatJob(raw: RawChatJob): ChatJob {
  const status = raw.status as ChatJob['status'];
  const result = raw.result as Record<string, unknown> | null | undefined;

  return {
    jobId: raw.job_id ?? '',
    status: JOB_STATUSES.includes(status) ? status : 'running',
    steps: (raw.steps ?? []).map(toChatStep),
    elapsedSeconds: raw.elapsed_seconds ?? 0,
    result: result ? toChatJobResult(result) : undefined,
    error: optional(raw.error),
  };
}

function toChatJobResult(raw: Record<string, unknown>): ChatJobResult {
  return {
    response: typeof raw.response === 'string' ? raw.response : '',
    thinkingTime: typeof raw.thinking_time === 'number' ? raw.thinking_time : 0,
    sources: Array.isArray(raw.sources) ? (raw.sources as string[]) : [],
    detectedSymbol: optional(raw.detected_symbol as string | null),
    sessionTitle: optional(raw.session_title as string | null),
  };
}

/** Whether a job has settled — used to stop polling. */
export function isSettled(job: ChatJob | undefined): boolean {
  return job?.status === 'done' || job?.status === 'error';
}

/**
 * A step as it is stored.
 *
 * Deliberately stricter than `RawChatStep`: that one describes what may arrive
 * and tolerates every field being absent, this one describes what we write and
 * has to be complete.
 */
export interface StoredChatStep {
  id: string;
  tool: string;
  label: string;
  status: string;
  detail: string | null;
  duration_seconds: number | null;
}

/** Back to the wire shape, for persisting a finished timeline. */
export function toStepRow(step: ChatStep): StoredChatStep {
  return {
    id: step.id,
    tool: step.tool,
    label: step.label,
    status: step.status,
    detail: step.detail ?? null,
    duration_seconds: step.durationSeconds ?? null,
  };
}

/**
 * Steps restored from history.
 *
 * `null` is what a message written before migration 009 has, and what a user
 * message has always had — both mean "no timeline", not "empty timeline".
 */
export function toStoredSteps(raw: unknown): ChatStep[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined;
  return raw.map((row, index) => toChatStep(row as RawChatStep, index));
}
