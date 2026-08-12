'use client';

import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

interface ProfileCardProps {
  title: string;
  icon?: LucideIcon;
  /** Right-aligned control in the header, e.g. an Edit button. */
  action?: ReactNode;
  /** Tints the header rule. Used once, by the delete-account card. */
  tone?: 'default' | 'danger';
  className?: string;
  children: ReactNode;
}

/**
 * The card shell every profile section uses.
 *
 * Matches the admin tabs rather than inventing a second look: `.surface` with a
 * hairline header at `px-4 py-2.5` and an `h2` at `text-md`. The page it
 * replaced used `p-6`, `space-y-6` and a `text-2xl font-bold` heading, which
 * made Profile the one screen in the app at a different density from every
 * other.
 *
 * `Panel` is not the right primitive here: it is built for fixed-height
 * dashboard widgets that scroll their own body, and these sections flow.
 */
export default function ProfileCard({
  title,
  icon: Icon,
  action,
  tone = 'default',
  className = '',
  children,
}: ProfileCardProps) {
  return (
    <section className={`surface overflow-hidden ${className}`}>
      <header
        className={`flex items-center justify-between gap-3 border-b px-4 py-2.5 ${
          tone === 'danger' ? 'border-down/40' : 'border-line'
        }`}
      >
        <h2
          className={`flex items-center gap-2 text-md font-semibold ${
            tone === 'danger' ? 'text-down' : 'text-fg'
          }`}
        >
          {Icon && <Icon className="h-3.5 w-3.5 text-fg-muted" />}
          {title}
        </h2>
        {action}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

/**
 * A label/value row. The fixed label column is what keeps the values aligned
 * down the card instead of stepping in and out with the label lengths.
 */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 sm:grid-cols-[96px_1fr] sm:items-baseline sm:gap-3">
      <div className="label">{label}</div>
      <div className="min-w-0 text-base text-fg">{children}</div>
    </div>
  );
}
