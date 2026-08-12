'use client';

import { useAdminOverview } from '@/hooks/useAdmin';

/**
 * The dashboard counters.
 *
 * Deliberately plain numbers rather than charts: with one board and a handful
 * of accounts, a sparkline would be decoration around a value that fits in four
 * characters.
 */
export default function OverviewTab() {
  const { data, isLoading, isError } = useAdminOverview();

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4" aria-hidden="true">
        {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
          <div key={i} className="surface shimmer h-20" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="surface px-4 py-8 text-center text-base text-fg-muted">
        The counters would not load.
      </div>
    );
  }

  const tiles: { label: string; value: number; tone?: 'warn' }[] = [
    { label: 'Users', value: data.total_users },
    { label: 'New this week', value: data.new_users_7d },
    { label: 'Suspended', value: data.banned_users, tone: data.banned_users ? 'warn' : undefined },
    { label: 'Free', value: data.plan_counts.free ?? 0 },
    { label: 'Pro', value: data.plan_counts.pro ?? 0 },
    { label: 'Whale', value: data.plan_counts.whale ?? 0 },
    { label: 'Posts', value: data.total_posts },
    { label: 'Comments', value: data.total_comments },
  ];

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(({ label, value, tone }) => (
          <div key={label} className="surface px-4 py-3">
            <div className="label">{label}</div>
            <div
              className={`font-mono text-xl tabnum ${tone === 'warn' ? 'text-warn' : 'text-fg'}`}
            >
              {value}
            </div>
          </div>
        ))}
      </div>

      <div className="surface px-4 py-3">
        <div className="label mb-1">Today</div>
        <p className="text-base text-fg-muted">
          <span className="font-mono text-fg tabnum">{data.posts_today}</span>{' '}
          {data.posts_today === 1 ? 'post' : 'posts'} since midnight UTC.
        </p>
      </div>
    </div>
  );
}
