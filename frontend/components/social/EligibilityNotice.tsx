'use client';

import Link from 'next/link';
import { CheckCircle2, Lock } from 'lucide-react';

import { daysUntilEligible, describeReason } from '@/lib/social';
import type { DmEligibility } from '@/lib/api';

/**
 * Why the composer is not there.
 *
 * A bare "you cannot send messages" leaves somebody unable to tell whether to
 * verify an address or simply wait a month, so this renders one row per unmet
 * requirement with the fix attached. The rules already satisfied are shown too,
 * greyed and ticked — a checklist that only lists failures reads as a wall.
 */
export default function EligibilityNotice({
  eligibility,
  reasons,
  className = '',
}: {
  /** The account-level verdict, for the standing requirements. */
  eligibility?: DmEligibility;
  /** Reasons from a specific refusal, which may include pair-level ones. */
  reasons?: string[];
  className?: string;
}) {
  const unmet = reasons ?? eligibility?.reasons ?? [];
  const met = metRequirements(eligibility, unmet);

  if (unmet.length === 0 && met.length === 0) return null;

  const waitDays = unmet.includes('account_too_new')
    ? daysUntilEligible(
        eligibility?.status.created_at,
        eligibility?.requirements.min_account_age_days ?? 0
      )
    : 0;

  return (
    <div className={`surface p-4 ${className}`}>
      <h3 className="flex items-center gap-2 text-md font-semibold text-fg">
        <Lock className="h-3.5 w-3.5 text-fg-muted" />
        Messaging is not open for you yet
      </h3>
      <p className="mt-1 text-sm text-fg-subtle">
        These rules exist so a brand-new account cannot message strangers in bulk. You can still
        read and reply in conversations you are already part of.
      </p>

      <ul className="mt-3 space-y-2.5">
        {unmet.map((reason) => {
          const copy = describeReason(reason);
          return (
            <li key={reason} className="flex items-start gap-2.5">
              <span
                aria-hidden="true"
                className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-down"
              />
              <div className="min-w-0">
                <p className="text-base text-fg">{copy.title}</p>
                <p className="text-sm text-fg-subtle">
                  {copy.detail}
                  {reason === 'account_too_new' && waitDays > 0 && (
                    <> {waitDays === 1 ? 'One more day.' : `About ${waitDays} more days.`}</>
                  )}
                </p>
                {copy.href && (
                  <Link
                    href={copy.href}
                    className="mt-1 inline-block text-sm text-accent hover:underline"
                  >
                    {copy.action ?? 'Fix this'}
                  </Link>
                )}
              </div>
            </li>
          );
        })}

        {met.map((label) => (
          <li key={label} className="flex items-start gap-2.5 text-fg-subtle">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-up" />
            <p className="text-base">{label}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The requirements this account already satisfies.
 *
 * Derived from `requirements` (what the server demands) intersected with
 * `status` (what the account has) — a rule that is switched off server-side is
 * not a requirement at all and must not appear as one the user has cleared.
 */
function metRequirements(eligibility: DmEligibility | undefined, unmet: string[]): string[] {
  if (!eligibility) return [];
  const labels: string[] = [];

  if (
    eligibility.requirements.email_verified &&
    eligibility.status.email_verified &&
    !unmet.includes('email_unverified')
  ) {
    labels.push('Email address verified');
  }
  if (
    eligibility.requirements.phone_verified &&
    eligibility.status.phone_verified &&
    !unmet.includes('phone_unverified')
  ) {
    labels.push('Phone number verified');
  }
  if (eligibility.requirements.min_account_age_days > 0 && !unmet.includes('account_too_new')) {
    labels.push('Account is old enough');
  }
  return labels;
}
