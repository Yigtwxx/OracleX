/**
 * Pure logic behind the Social tab.
 *
 * Kept free of JSX on purpose: `vitest.config.mts` collects `lib/**\/*.test.ts`
 * under a node environment, so anything that needs a test has to live here
 * rather than inside a component.
 */

/** Matched by `MAX_BODY` in services/social/messages.py and the CHECK in 013. */
export const MAX_MESSAGE_LENGTH = 2000;

/**
 * The reasons the server may give for refusing a send.
 *
 * These strings are the API contract — `services/social/eligibility.py` emits
 * them and `EligibilityNotice` renders one row per reason. Renaming one on
 * either side silently drops a row rather than failing loudly, which is why
 * they are enumerated here instead of being interpolated.
 */
export type DmBlockReason =
  | 'email_unverified'
  | 'phone_unverified'
  | 'account_too_new'
  | 'recipient_blocked_you'
  | 'you_blocked_recipient'
  | 'recipient_disabled_dms'
  | 'cannot_message_yourself';

interface ReasonCopy {
  title: string;
  detail: string;
  /** Where the user goes to fix it, when that is somewhere. */
  href?: string;
  action?: string;
}

const REASON_COPY: Record<DmBlockReason, ReasonCopy> = {
  email_unverified: {
    title: 'Verify your email address',
    detail: 'Open the link we sent you. It only has to be done once.',
    href: '/profile',
    action: 'Go to Profile',
  },
  phone_unverified: {
    title: 'Verify a phone number',
    detail: 'Add a number under Profile → Security and enter the code we text you.',
    href: '/profile',
    action: 'Go to Security',
  },
  account_too_new: {
    title: 'Your account is too new',
    detail: 'Messaging opens up once your account has been around a while.',
  },
  recipient_blocked_you: {
    title: 'This person has blocked you',
    detail: 'You cannot start or continue a conversation with them.',
  },
  you_blocked_recipient: {
    title: 'You blocked this person',
    detail: 'Unblock them from Social → Blocked to message them again.',
  },
  recipient_disabled_dms: {
    title: 'This person is not accepting messages',
    detail: 'They have turned direct messages off for their account.',
  },
  cannot_message_yourself: {
    title: 'That is your own account',
    detail: 'Pick somebody else to message.',
  },
};

/**
 * Explain a refusal.
 *
 * Falls back to a generic row rather than dropping an unknown code: a server
 * that grows a new reason should still render something the user can read.
 */
export function describeReason(reason: string): ReasonCopy {
  return (
    REASON_COPY[reason as DmBlockReason] ?? {
      title: 'You cannot message this person yet',
      detail: 'One of the requirements for sending messages is not met.',
    }
  );
}

/**
 * Days remaining before an account clears the age requirement.
 *
 * Returns 0 once it has. Rounded up so "1 day left" never displays for an
 * account that still has 23 hours to wait.
 */
export function daysUntilEligible(
  createdAt: string | null | undefined,
  minAgeDays: number,
  now: Date = new Date()
): number {
  if (!createdAt || minAgeDays <= 0) return 0;
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) return 0;
  const elapsedDays = (now.getTime() - created.getTime()) / 86_400_000;
  return Math.max(0, Math.ceil(minAgeDays - elapsedDays));
}

/** Unread pills stop counting at 99 — past that the exact number tells nobody anything. */
export function formatUnread(count: number): string {
  if (count <= 0) return '';
  return count > 99 ? '99+' : String(count);
}

/** One line of preview in the conversation list, collapsed to a single line. */
export function previewText(body: string | null | undefined, limit = 60): string {
  if (!body) return 'No messages yet';
  const flat = body.replace(/\s+/g, ' ').trim();
  if (!flat) return 'No messages yet';
  return flat.length <= limit ? flat : `${flat.slice(0, limit - 1)}…`;
}

export interface DayGroup<T> {
  /** `YYYY-MM-DD` in local time — the key the separator renders from. */
  day: string;
  items: T[];
}

/**
 * Split a thread into day-separated runs.
 *
 * Local time, not UTC: the separator says "today" to the person reading it, and
 * a UTC boundary would move that line by up to a day depending on where they
 * are. Messages are assumed already sorted oldest-first, which is what the
 * backend returns.
 */
export function groupByDay<T>(items: T[], timestampOf: (item: T) => string): DayGroup<T>[] {
  const groups: DayGroup<T>[] = [];
  for (const item of items) {
    const parsed = new Date(timestampOf(item));
    const day = Number.isNaN(parsed.getTime()) ? 'unknown' : toLocalDayKey(parsed);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.items.push(item);
    else groups.push({ day, items: [item] });
  }
  return groups;
}

function toLocalDayKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

/** "Today" / "Yesterday" / a written date, for the separator between day runs. */
export function formatDayLabel(dayKey: string, now: Date = new Date()): string {
  if (dayKey === 'unknown') return '';
  if (dayKey === toLocalDayKey(now)) return 'Today';

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (dayKey === toLocalDayKey(yesterday)) return 'Yesterday';

  // Parsed as local midnight rather than through `new Date(dayKey)`, which
  // reads a bare `YYYY-MM-DD` as UTC and renders the previous day west of
  // Greenwich.
  const [year, month, day] = dayKey.split('-').map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    year: year === now.getFullYear() ? undefined : 'numeric',
  });
}

/**
 * Whether a phone number is plausibly E.164.
 *
 * Deliberately loose. Supabase is the authority on whether a number can receive
 * an SMS; this only stops the obvious mistakes before an OTP request is spent,
 * because each one costs a message.
 */
export function isValidPhone(raw: string): boolean {
  return /^\+[1-9]\d{7,14}$/.test(raw.trim());
}

/**
 * Coerce typed input toward E.164.
 *
 * Strips spaces, hyphens and brackets, and rewrites a leading `00` to `+`.
 * A bare national number is left alone rather than guessed at — there is no
 * country to guess from, and prefixing the wrong one sends the code elsewhere.
 */
export function normalisePhone(raw: string): string {
  const stripped = raw.replace(/[\s\-().]/g, '');
  if (stripped.startsWith('00')) return `+${stripped.slice(2)}`;
  return stripped;
}

/** The OTP is six digits; anything else is not worth a round trip. */
export function isValidOtp(raw: string): boolean {
  return /^\d{6}$/.test(raw.trim());
}
