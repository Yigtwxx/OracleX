/**
 * The mail channel: confirming an address, and mailing a fired alarm to it.
 *
 * A fourth delivery route alongside the toast, the sound and the OS
 * notification — and the only one that survives the browser being minimised
 * behind other windows. It does *not* survive the tab being closed: the engine
 * that decides an alarm fired runs here, so nothing is evaluated once the page
 * is gone. `AlarmEmailSettings` says that in the UI rather than letting the user
 * discover it from an alarm that never arrived.
 *
 * Kept out of `lib/api.ts` because that file is the market-data surface and this
 * is the only place in the app that talks to `/api/alarms`.
 */

import { ApiError, apiFetch } from '@/lib/api';
import type { Alarm } from './types';

/** How the message is coloured. Mirrors the backend's `tone` field exactly. */
export type AlarmMailTone = 'up' | 'down' | 'warn' | 'accent';

/** A confirmed address and the token that proves it was confirmed. */
export interface AlarmEmailIdentity {
  address: string;
  token: string;
}

export interface AlarmMailRequest {
  eventId: string;
  sourceLabel: string;
  subjectLine: string;
  observed: string;
  rule: string;
  firedAtLabel: string;
  tone: AlarmMailTone;
  triggerCount?: number;
  /** The sentence the message leads with, from `describeMailHeadline`. */
  headline?: string;
  /** The supporting line under it, from `describeMailLead`. */
  lead?: string;
  /** Threshold alarms only — the figures row drops the column without them. */
  threshold?: string;
  distance?: string;
}

/**
 * Whether this deployment can send mail at all.
 *
 * Asked once when the panel opens. A deployment with no SMTP configured is the
 * default, not a fault, so the panel renders a short explanation instead of a
 * form whose submit button would answer 503.
 */
export async function fetchAlarmEmailStatus(): Promise<boolean> {
  const data = await apiFetch<{ enabled: boolean }>('/api/alarms/email/status', {
    anonymous: true,
  });
  return data.enabled;
}

export async function requestAlarmEmailCode(email: string): Promise<void> {
  await apiFetch<{ sent: boolean }>('/api/alarms/email/request-code', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email }),
  });
}

export async function confirmAlarmEmailCode(
  email: string,
  code: string
): Promise<AlarmEmailIdentity> {
  const data = await apiFetch<{ email: string; token: string }>('/api/alarms/email/confirm', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({ email, code }),
  });
  // The backend's normalized form, not what was typed: it is what the token was
  // signed over, and storing the typed version would break every later send.
  return { address: data.email, token: data.token };
}

/**
 * Mail one fired alarm.
 *
 * Resolves to `false` when the backend recognised it as a duplicate it had
 * already delivered — a success, not a failure, and the caller logs neither.
 */
export async function sendAlarmEmail(
  identity: AlarmEmailIdentity,
  request: AlarmMailRequest
): Promise<boolean> {
  const data = await apiFetch<{ sent: boolean }>('/api/alarms/email/notify', {
    method: 'POST',
    anonymous: true,
    body: JSON.stringify({
      email: identity.address,
      token: identity.token,
      event_id: request.eventId,
      source_label: request.sourceLabel,
      subject_line: request.subjectLine,
      observed: request.observed,
      rule: request.rule,
      fired_at_label: request.firedAtLabel,
      tone: request.tone,
      trigger_count: request.triggerCount,
      headline: request.headline ?? '',
      lead: request.lead ?? '',
      threshold: request.threshold ?? null,
      distance: request.distance ?? null,
    }),
  });
  return data.sent;
}

/**
 * True when the backend refused the stored token rather than failing to send.
 *
 * The two need different handling and the status code is the only thing that
 * separates them: 403 means the confirmation no longer stands — the signing
 * secret was rotated, or this token was never issued — and the address has to be
 * confirmed again. Anything else is transient and the address stays.
 */
export function isAlarmEmailRejected(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/**
 * Which way the reading broke, as a colour.
 *
 * Read from the alarm's own condition rather than from the source, because the
 * source does not know: a funding rate crossing below zero and a price falling
 * through a floor are the same event to a reader and should look the same. The
 * kinds that have no direction — a keyword hit, a countdown, a state change —
 * stay accent blue rather than borrowing a colour that would imply one.
 */
export function toneForAlarm(alarm: Alarm): AlarmMailTone {
  switch (alarm.condition.kind) {
    case 'threshold':
      return alarm.condition.op === 'above' ? 'up' : 'down';
    case 'state':
      return 'warn';
    default:
      return 'accent';
  }
}

/**
 * The trigger time, written for the reader's own clock.
 *
 * Formatted here and sent as a string because this is the only process that
 * knows the reader's timezone — the backend would have to guess, and a mail
 * saying 11:32 for an alarm the user watched fire at 14:32 reads as a bug in
 * the alarm rather than in the timestamp.
 */
export function formatFiredAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('en-US', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── SMTP relay configuration (admin only) ───────────────────────────────────

/**
 * The relay as the backend has it.
 *
 * `hasPassword` rather than the password: the backend never returns one, so an
 * edit that leaves the field blank means "keep what is stored". `source` is
 * `panel` when an admin set these here, `env` when they came from `backend/.env`,
 * and `none` when nothing is configured — the panel says which, because an
 * admin editing a deployment they did not set up should know what they are
 * about to override.
 */
export interface SmtpSettings {
  host: string;
  port: number;
  user: string;
  ssl: boolean;
  starttls: boolean;
  fromAddress: string;
  fromName: string;
  replyTo: string;
  hasPassword: boolean;
  sender: string;
  configured: boolean;
  source: 'panel' | 'env' | 'none';
}

/** One save. Every field is optional; omitted means "do not change". */
export interface SmtpSettingsPatch {
  host?: string;
  port?: number;
  user?: string;
  password?: string;
  ssl?: boolean;
  starttls?: boolean;
  fromAddress?: string;
  fromName?: string;
  replyTo?: string;
}

interface SmtpSettingsWire {
  host: string;
  port: number;
  user: string;
  ssl: boolean;
  starttls: boolean;
  from_address: string;
  from_name: string;
  reply_to: string;
  has_password: boolean;
  sender: string;
  configured: boolean;
  source: string;
}

function toSmtpSettings(wire: SmtpSettingsWire): SmtpSettings {
  return {
    host: wire.host,
    port: wire.port,
    user: wire.user,
    ssl: wire.ssl,
    starttls: wire.starttls,
    fromAddress: wire.from_address,
    fromName: wire.from_name,
    replyTo: wire.reply_to,
    hasPassword: wire.has_password,
    sender: wire.sender,
    configured: wire.configured,
    source: wire.source === 'panel' || wire.source === 'env' ? wire.source : 'none',
  };
}

export async function fetchSmtpSettings(): Promise<SmtpSettings> {
  return toSmtpSettings(await apiFetch<SmtpSettingsWire>('/api/alarms/email/smtp'));
}

export async function saveSmtpSettings(patch: SmtpSettingsPatch): Promise<SmtpSettings> {
  const body: Record<string, unknown> = {};
  if (patch.host !== undefined) body.host = patch.host;
  if (patch.port !== undefined) body.port = patch.port;
  if (patch.user !== undefined) body.user = patch.user;
  if (patch.password !== undefined) body.password = patch.password;
  if (patch.ssl !== undefined) body.ssl = patch.ssl;
  if (patch.starttls !== undefined) body.starttls = patch.starttls;
  if (patch.fromAddress !== undefined) body.from_address = patch.fromAddress;
  if (patch.fromName !== undefined) body.from_name = patch.fromName;
  if (patch.replyTo !== undefined) body.reply_to = patch.replyTo;

  const wire = await apiFetch<SmtpSettingsWire>('/api/alarms/email/smtp', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return toSmtpSettings(wire);
}

export async function clearSmtpSettings(): Promise<SmtpSettings> {
  const wire = await apiFetch<SmtpSettingsWire>('/api/alarms/email/smtp', { method: 'DELETE' });
  return toSmtpSettings(wire);
}

/** Send one message through the relay as configured. `to` defaults to the admin. */
export async function testSmtpRelay(to?: string): Promise<void> {
  await apiFetch<{ sent: boolean }>('/api/alarms/email/smtp/test', {
    method: 'POST',
    body: JSON.stringify({ to: to ?? null }),
  });
}
