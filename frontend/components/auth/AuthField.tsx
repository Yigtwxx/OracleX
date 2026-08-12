'use client';

import { useId, type InputHTMLAttributes, type ReactNode } from 'react';

/**
 * The one input class string used by every auth form.
 *
 * Exported rather than duplicated: five forms with five copies of a Tailwind
 * string is how a focus ring ends up different on one screen. Lifted verbatim
 * from the admin dialogs so the auth card looks like the rest of the app.
 */
export const INPUT_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg transition-colors placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-50';

interface AuthFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'className' | 'id'> {
  label: string;
  /** Rendered under the input in red, and wired to the input via aria. */
  error?: string;
  /** Quiet helper text. Hidden while an error is showing — one message at a time. */
  hint?: string;
  /** Optional trailing control, e.g. a show/hide password toggle. */
  action?: ReactNode;
}

export default function AuthField({ label, error, hint, action, ...props }: AuthFieldProps) {
  const id = useId();
  const messageId = `${id}-message`;

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="label">
          {label}
        </label>
        {action}
      </div>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? messageId : undefined}
        className={INPUT_CLASS}
        {...props}
      />
      {(error || hint) && (
        <p id={messageId} className={`mt-1 text-sm ${error ? 'text-down' : 'text-fg-subtle'}`}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

type NoticeTone = 'error' | 'success' | 'warn';

const NOTICE_CLASS: Record<NoticeTone, string> = {
  error: 'border-down/40 bg-down-bg text-down',
  success: 'border-up/40 bg-up-bg text-up',
  warn: 'border-warn/40 bg-warn-bg text-warn',
};

/**
 * A form-level message.
 *
 * Separate from field errors because the two mean different things: a field
 * error is "fix this box", a notice is "here is what happened". The old page
 * used a single `error` string for both, and told success from failure by
 * checking whether it contained the words "Check your email".
 */
export function FormNotice({ tone, children }: { tone: NoticeTone; children: ReactNode }) {
  return (
    <p
      role={tone === 'error' ? 'alert' : 'status'}
      className={`rounded-md border px-2.5 py-2 text-base ${NOTICE_CLASS[tone]}`}
    >
      {children}
    </p>
  );
}
