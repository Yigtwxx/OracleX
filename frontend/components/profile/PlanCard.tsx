'use client';

import { Check, CreditCard } from 'lucide-react';

import ProfileCard from '@/components/profile/ProfileCard';
import type { Profile } from '@/lib/api';

type Plan = 'free' | 'pro' | 'whale';

/** Mirrors `get_plan_features` in services/profile_service.py. */
const PLANS: Record<Plan, { name: string; price: number; features: string[] }> = {
  free: {
    name: 'Free',
    price: 0,
    features: ['15 min news delay', 'Basic charts', '5 AI queries a day'],
  },
  pro: {
    name: 'Pro',
    price: 29,
    features: [
      'Real-time news feed',
      'Live liquidation heatmaps',
      'Unlimited AI analysis',
      'Advanced technical alerts',
    ],
  },
  whale: {
    name: 'Whale',
    price: 99,
    features: ['Everything in Pro', 'On-chain whale alerts', 'API access', 'Priority support'],
  },
};

/**
 * What the account is on today.
 *
 * Read-only, and that is the honest shape: there is no payment integration in
 * this project, and the upgrade endpoint behind the old "Contact Sales" buttons
 * is admin-only. The page used to render three large pricing tiles whose
 * buttons had no click handler at all — a storefront that could not sell.
 */
export default function PlanCard({ profile }: { profile: Profile | undefined }) {
  const plan = (profile?.subscription_plan ?? 'free') as Plan;
  const details = PLANS[plan] ?? PLANS.free;

  const used = profile?.ai_queries_today ?? 0;
  const limit = profile?.ai_query_limit ?? 5;
  // The paid plans store their "unlimited" as 999999; a meter against that is
  // a permanently empty bar, so say the word instead of drawing it.
  const metered = limit < 1000;
  const ratio = metered ? Math.min(1, used / Math.max(1, limit)) : 0;

  return (
    <ProfileCard title="Plan" icon={CreditCard}>
      <div className="space-y-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-md font-semibold text-fg">{details.name}</span>
          <span className="font-mono text-base tabnum text-fg-muted">${details.price}/mo</span>
        </div>

        <ul className="space-y-1.5">
          {details.features.map((feature) => (
            <li key={feature} className="flex items-start gap-2 text-base text-fg-muted">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-subtle" />
              {feature}
            </li>
          ))}
        </ul>

        <div className="border-t border-line pt-3">
          <div className="mb-1.5 flex items-baseline justify-between gap-3">
            <span className="label">AI queries today</span>
            <span className="font-mono text-sm tabnum text-fg-muted">
              {metered ? `${used} / ${limit}` : 'Unlimited'}
            </span>
          </div>
          {metered && (
            <div
              role="meter"
              aria-valuenow={used}
              aria-valuemin={0}
              aria-valuemax={limit}
              aria-label="AI queries used today"
              className="h-1 w-full overflow-hidden rounded-full bg-surface-2"
            >
              <div
                className={`h-full transition-[width] ${ratio >= 1 ? 'bg-warn' : 'bg-accent'}`}
                style={{ width: `${ratio * 100}%` }}
              />
            </div>
          )}
        </div>

        <p className="text-sm text-fg-subtle">
          Plan changes are handled manually — there is no self-service checkout yet.
        </p>
      </div>
    </ProfileCard>
  );
}
