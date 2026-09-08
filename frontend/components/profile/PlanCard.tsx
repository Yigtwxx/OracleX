'use client';

import { CreditCard } from 'lucide-react';

import ProfileCard from '@/components/profile/ProfileCard';
import type { Profile } from '@/lib/api';

type Plan = 'free' | 'pro' | 'whale';

const PLAN_NAMES: Record<Plan, string> = {
  free: 'Free',
  pro: 'Pro',
  whale: 'Whale',
};

/**
 * What the account is on today, and what that does — which is nothing.
 *
 * This card used to render a price, a feature list and a "0 / 5 AI queries
 * today" meter. All three were fiction on a self-hosted install: there is no
 * payment integration, `increment_ai_queries` is called by no AI path, and
 * `ai_queries_today` is therefore always zero. A new reader read "5 AI queries
 * a day" as a cap they were about to hit and a bill they had to pay to pass it,
 * when the truth is that every account here has identical access.
 *
 * A meter that cannot move is worse than no meter, so the real figures live in
 * the Usage card and this one says only what the label means.
 */
export default function PlanCard({ profile }: { profile: Profile | undefined }) {
  const plan = (profile?.subscription_plan ?? 'free') as Plan;

  return (
    <ProfileCard title="Plan" icon={CreditCard}>
      <div className="space-y-3">
        <span className="text-md font-semibold text-fg">{PLAN_NAMES[plan] ?? plan}</span>

        <p className="text-sm text-fg-subtle">
          Nothing on this install is metered or billed. The plan is a label an admin can set; no AI
          feature checks it, and every account has the same access. What you actually spend is in
          Usage below.
        </p>
      </div>
    </ProfileCard>
  );
}
