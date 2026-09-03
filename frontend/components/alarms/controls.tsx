'use client';

import type { ReactNode } from 'react';

/**
 * The form vocabulary this dialog needs.
 *
 * `components/ui/` has no Button, Input or Tabs primitive — the app writes those
 * as inline Tailwind strings, duplicated per call site. These wrappers keep the
 * alarm builder from adding a dozen more copies, and every class string below is
 * lifted verbatim from an existing call site (AuthField, BanDialog, FeedToolbar)
 * so the dialog inherits the house look rather than inventing one.
 */

export const INPUT_CLASS =
  'w-full rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-base text-fg transition-colors placeholder:text-fg-subtle focus:border-accent focus:outline-none disabled:opacity-50';

export const PRIMARY_BUTTON_CLASS =
  'px-3 py-1.5 bg-accent text-white text-base rounded-md hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed';

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div>
      <span className="label mb-1.5 block">{label}</span>
      {children}
      {hint && <p className="mt-1 text-xs text-fg-subtle">{hint}</p>}
    </div>
  );
}

export interface Choice {
  value: string;
  label: string;
}

/** Quiet segmented group — one of N, mutually exclusive. */
export function Segmented({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: Choice[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex rounded-md border border-line p-0.5 gap-0.5"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={`rounded px-2.5 py-1 text-base transition-colors ${
              active ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/** Accent-active pill, for a multi-select set. */
export function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1 text-base transition-colors ${
        active
          ? 'border-accent bg-accent-bg text-accent'
          : 'border-line text-fg-muted hover:border-line-strong hover:text-fg'
      }`}
    >
      {children}
    </button>
  );
}

export function Select({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Choice[];
  ariaLabel: string;
}) {
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={INPUT_CLASS}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
