'use client';

import { Hash, Users } from 'lucide-react';

import { useCommunitySidebar } from '@/hooks/useCommunity';

const GUIDELINES = [
  'Say what would change your mind. A thesis without an invalidation is a hope.',
  'Bring the number. "Funding is negative" beats "funding looks bad".',
  'Disclose a position when you have one in the ticker you are posting about.',
  'Nothing here is advice, and nobody here owes you an exit.',
];

function StatRow({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="label">{label}</span>
      <span className="font-mono text-base text-fg tabnum">{value ?? '—'}</span>
    </div>
  );
}

/**
 * The right rail.
 *
 * Everything here is derived from posts the board already holds — trending
 * tickers are an aggregate over `asset_symbol`, the counters are counts. No new
 * data source, so nothing here can go stale independently of the feed.
 */
export default function CommunitySidebar({
  onSelectSymbol,
}: {
  onSelectSymbol: (symbol: string) => void;
}) {
  const { data, isLoading } = useCommunitySidebar();

  return (
    <aside className="flex w-72 shrink-0 flex-col gap-3">
      <section className="surface p-3">
        <h2 className="label mb-2.5 flex items-center gap-1.5">
          <Hash className="h-3 w-3" />
          Trending this week
        </h2>

        {isLoading ? (
          <div className="h-20 shimmer rounded-md" />
        ) : data && data.trending.length > 0 ? (
          <ul className="space-y-0.5">
            {data.trending.map((asset) => (
              <li key={asset.asset_symbol}>
                <button
                  type="button"
                  onClick={() => onSelectSymbol(asset.asset_symbol)}
                  className="flex w-full items-baseline justify-between rounded px-1.5 py-1 text-left transition-colors hover:bg-surface-2"
                >
                  <span className="font-mono text-base text-fg">{asset.asset_symbol}</span>
                  <span className="font-mono text-xs text-fg-subtle tabnum">
                    {asset.post_count} {asset.post_count === 1 ? 'post' : 'posts'}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-fg-subtle">No tickers have come up in the last seven days.</p>
        )}
      </section>

      <section className="surface space-y-2 p-3">
        <h2 className="label mb-2.5 flex items-center gap-1.5">
          <Users className="h-3 w-3" />
          Board
        </h2>
        <StatRow label="Posts" value={data?.stats.total_posts} />
        <StatRow label="Last 24h" value={data?.stats.posts_today} />
        <StatRow label="Contributors" value={data?.stats.contributors} />
      </section>

      <section className="surface p-3">
        <h2 className="label mb-2.5">House rules</h2>
        <ul className="space-y-2">
          {GUIDELINES.map((rule) => (
            <li key={rule} className="text-sm leading-relaxed text-fg-subtle">
              {rule}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
