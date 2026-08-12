'use client';

import { useState } from 'react';
import { Activity, ClipboardList, MessageSquare, Shield, Users } from 'lucide-react';

import AuditTab from '@/components/admin/AuditTab';
import ContentTab from '@/components/admin/ContentTab';
import OverviewTab from '@/components/admin/OverviewTab';
import UsersTab from '@/components/admin/UsersTab';
import { useAuth } from '@/contexts/AuthContext';
import { useIsAdmin } from '@/hooks/useAdmin';

type TabKey = 'overview' | 'users' | 'content' | 'audit';

const TABS: { key: TabKey; label: string; icon: typeof Users }[] = [
  { key: 'overview', label: 'Overview', icon: Activity },
  { key: 'users', label: 'Users', icon: Users },
  { key: 'content', label: 'Content', icon: MessageSquare },
  { key: 'audit', label: 'Audit', icon: ClipboardList },
];

/**
 * The admin panel.
 *
 * The gate here is cosmetic and deliberately so: every route behind it 403s for
 * a non-admin, and this component only decides what to render while that is
 * true. What it renders to a signed-in non-admin is a plain "does not exist" —
 * saying "you are not an admin" would confirm the route is real and turn the
 * page into a probe.
 */
export default function AdminPage() {
  const { user, loading: authLoading } = useAuth();
  const session = useIsAdmin();
  const [tab, setTab] = useState<TabKey>('overview');

  if (authLoading || (user && session.isLoading)) {
    return <Centered>{<div className="surface shimmer h-40 w-full max-w-md" />}</Centered>;
  }

  if (!user) {
    return (
      <Centered>
        <div className="surface px-6 py-10 text-center">
          <Shield className="mx-auto mb-3 h-6 w-6 text-fg-subtle" />
          <h1 className="mb-1.5 text-md font-semibold text-fg">Sign in to continue</h1>
          <p className="text-base text-fg-muted">
            This area is restricted. Sign in from the profile page.
          </p>
        </div>
      </Centered>
    );
  }

  // Covers both "the answer was no" and "the request failed" — neither is a
  // state in which the panel should render.
  if (!session.data?.is_admin) {
    return (
      <Centered>
        <div className="surface px-6 py-10 text-center">
          <h1 className="mb-1.5 text-md font-semibold text-fg">This page does not exist.</h1>
          <p className="text-base text-fg-muted">Check the address and try again.</p>
        </div>
      </Centered>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex shrink-0 flex-col justify-between gap-3 border-b border-line bg-surface px-4 py-3 sm:flex-row sm:items-center">
        <div>
          <h1 className="flex items-center gap-2 text-md font-semibold text-fg">
            <Shield className="h-3.5 w-3.5 text-fg-muted" />
            Admin
          </h1>
          <p className="max-w-xl text-xs text-fg-subtle">
            Moderation, accounts and the record of what was done to them.
          </p>
        </div>

        {/* Which account is acting. One admin today, but every destructive
            action below is attributed to whoever is signed in. */}
        <span className="font-mono text-xs text-fg-subtle">{session.data.email}</span>
      </header>

      <div className="shrink-0 border-b border-line bg-bg px-4 py-2">
        <div
          role="group"
          aria-label="Admin sections"
          className="flex items-center gap-1 overflow-x-auto custom-scrollbar"
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
        {tab === 'overview' && <OverviewTab />}
        {tab === 'users' && <UsersTab currentUserId={user.id} />}
        {tab === 'content' && <ContentTab />}
        {tab === 'audit' && <AuditTab />}
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full items-center justify-center p-6">{children}</div>;
}
