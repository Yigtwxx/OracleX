'use client';

import { useState } from 'react';
import { Bot, Lock, UserCircle } from 'lucide-react';

import AuthCard from '@/components/auth/AuthCard';
import AIProviderSettings from '@/components/profile/AIProviderSettings';
import SocialLinksCard from '@/components/profile/SocialLinksCard';
import DangerZone from '@/components/profile/DangerZone';
import EmailVerificationBanner from '@/components/profile/EmailVerificationBanner';
import IdentityCard from '@/components/profile/IdentityCard';
import MessagingCard from '@/components/profile/MessagingCard';
import PhoneField from '@/components/profile/PhoneField';
import PlanCard from '@/components/profile/PlanCard';
import ProfileHeader from '@/components/profile/ProfileHeader';
import SecurityCard from '@/components/profile/SecurityCard';
import { useAuth } from '@/contexts/AuthContext';
import { useProfile } from '@/hooks/useProfile';

type TabKey = 'account' | 'security' | 'ai';

const TABS: { key: TabKey; label: string; icon: typeof UserCircle }[] = [
  { key: 'account', label: 'Account', icon: UserCircle },
  { key: 'security', label: 'Security', icon: Lock },
  { key: 'ai', label: 'AI Provider', icon: Bot },
];

/**
 * The profile screen — a shell, by design.
 *
 * This file was 734 lines holding the login form, the sign-up form, a theme
 * picker, a language picker, three dead OAuth buttons and a pricing table. Each
 * section now owns its own file under `components/profile/`, and the signed-out
 * half lives under `components/auth/` because it renders for people who have no
 * profile at all.
 */
export default function ProfilePage() {
  const { user, loading: authLoading } = useAuth();
  const { data: profile, isLoading: profileLoading } = useProfile();
  const [tab, setTab] = useState<TabKey>('account');

  if (authLoading) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="surface shimmer h-40 w-full max-w-sm" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="custom-scrollbar h-full overflow-y-auto p-6">
        <div className="flex min-h-full items-center justify-center">
          <AuthCard />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <ProfileHeader user={user} profile={profile} />

      {!user.email_confirmed_at && user.email && <EmailVerificationBanner email={user.email} />}

      <div className="shrink-0 border-b border-line bg-bg px-4 py-2">
        <div
          role="group"
          aria-label="Profile sections"
          className="custom-scrollbar flex items-center gap-1 overflow-x-auto"
        >
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              aria-pressed={tab === key}
              onClick={() => setTab(key)}
              className={`flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-base transition-colors ${
                tab === key ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto p-4">
        {tab === 'account' &&
          (profileLoading ? (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div className="surface shimmer h-72" />
              <div className="surface shimmer h-72" />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <IdentityCard user={user} profile={profile} />
              <PlanCard profile={profile} />
              <div className="lg:col-span-2">
                <SocialLinksCard />
              </div>
            </div>
          ))}

        {tab === 'security' && (
          <div className="space-y-3">
            <SecurityCard email={user.email ?? ''} />
            <PhoneField user={user} />
            <MessagingCard />
            <DangerZone email={user.email ?? ''} />
          </div>
        )}

        {tab === 'ai' && <AIProviderSettings />}
      </div>
    </div>
  );
}
