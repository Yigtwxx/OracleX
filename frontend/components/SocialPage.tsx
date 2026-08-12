'use client';

import { useState } from 'react';
import { BarChart3, Eye, MessagesSquare } from 'lucide-react';

import AuthCard from '@/components/auth/AuthCard';
import ActivityTab from '@/components/social/ActivityTab';
import MessagesTab from '@/components/social/MessagesTab';
import PreviewTab from '@/components/social/PreviewTab';
import { useAuth } from '@/contexts/AuthContext';
import { useUnreadCount } from '@/hooks/useSocial';
import { formatUnread } from '@/lib/social';

type TabKey = 'messages' | 'activity' | 'preview';

const TABS: { key: TabKey; label: string; icon: typeof Eye }[] = [
  { key: 'messages', label: 'Messages', icon: MessagesSquare },
  { key: 'activity', label: 'Activity', icon: BarChart3 },
  { key: 'preview', label: 'Preview', icon: Eye },
];

/**
 * The Social tab — a shell, like ProfilePage.
 *
 * Three sections that answer three different questions about *you as a member*:
 * who is talking to you, how your writing has done, and what strangers see. The
 * sub-tab pattern, spacing and density are lifted from `ProfilePage` on purpose
 * — a second tab bar at a different size would make this the one screen in the
 * app that looks bolted on.
 *
 * Signed-out renders the auth card. Every route behind this is authenticated
 * server-side; this is the polite half.
 */
export default function SocialPage() {
  const { user, loading } = useAuth();
  const [tab, setTab] = useState<TabKey>('messages');
  const { data: unread } = useUnreadCount();

  if (loading) {
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

  const badge = formatUnread(unread ?? 0);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line bg-bg px-4 py-2">
        <div
          role="group"
          aria-label="Social sections"
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
              {key === 'messages' && badge && (
                <span className="rounded-full bg-accent px-1.5 text-2xs font-semibold text-white">
                  {badge}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {tab === 'messages' && <MessagesTab viewerId={user.id} />}
        {tab === 'activity' && <ActivityTab userId={user.id} />}
        {tab === 'preview' && <PreviewTab userId={user.id} />}
      </div>
    </div>
  );
}
