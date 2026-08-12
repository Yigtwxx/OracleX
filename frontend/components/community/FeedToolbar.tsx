'use client';

import { Clock, Filter, Flame, TrendingUp, X } from 'lucide-react';

import type { CommunityFeedSort, CommunityPostType } from '@/lib/api';

const SORTS: { key: CommunityFeedSort; label: string; icon: typeof Flame; hint: string }[] = [
  { key: 'hot', label: 'Hot', icon: Flame, hint: 'Score weighted against age' },
  { key: 'new', label: 'New', icon: Clock, hint: 'Most recent first' },
  { key: 'top', label: 'Top', icon: TrendingUp, hint: 'Highest score first' },
];

interface FeedToolbarProps {
  sort: CommunityFeedSort;
  onSortChange: (sort: CommunityFeedSort) => void;
  type: CommunityPostType | 'all';
  onTypeChange: (type: CommunityPostType | 'all') => void;
  symbol?: string;
  onClearSymbol: () => void;
  scope: 'all' | 'mine';
  onScopeChange: (scope: 'all' | 'mine') => void;
  canFilterMine: boolean;
}

export default function FeedToolbar({
  sort,
  onSortChange,
  type,
  onTypeChange,
  symbol,
  onClearSymbol,
  scope,
  onScopeChange,
  canFilterMine,
}: FeedToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {/* Sort — the primary control, so it reads as a segmented group. */}
      <div role="group" aria-label="Sort posts" className="flex gap-0.5">
        {SORTS.map(({ key, label, icon: Icon, hint }) => {
          const active = sort === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onSortChange(key)}
              aria-pressed={active}
              title={hint}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm transition-colors ${
                active ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          );
        })}
      </div>

      {canFilterMine && (
        <div role="group" aria-label="Whose posts" className="flex gap-0.5">
          <button
            type="button"
            onClick={() => onScopeChange('all')}
            aria-pressed={scope === 'all'}
            className={`rounded-md px-2.5 py-1 text-sm transition-colors ${
              scope === 'all' ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
            }`}
          >
            Everyone
          </button>
          <button
            type="button"
            onClick={() => onScopeChange('mine')}
            aria-pressed={scope === 'mine'}
            className={`rounded-md px-2.5 py-1 text-sm transition-colors ${
              scope === 'mine' ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
            }`}
          >
            My posts
          </button>
        </div>
      )}

      <div className="ml-auto flex items-center gap-2">
        {symbol && (
          <button
            type="button"
            onClick={onClearSymbol}
            className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 font-mono text-xs text-fg transition-colors hover:border-line-strong"
            aria-label={`Stop filtering by ${symbol}`}
          >
            {symbol}
            <X className="h-3 w-3 text-fg-subtle" />
          </button>
        )}

        <div className="flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1 transition-colors focus-within:border-accent">
          <Filter className="h-3 w-3 text-fg-subtle" />
          <select
            value={type}
            onChange={(event) => onTypeChange(event.target.value as CommunityPostType | 'all')}
            aria-label="Filter posts by type"
            className="cursor-pointer bg-transparent text-sm text-fg-muted focus:outline-none"
          >
            <option value="all">All types</option>
            <option value="thought">Thoughts</option>
            <option value="question">Questions</option>
            <option value="analysis">Analysis</option>
          </select>
        </div>
      </div>
    </div>
  );
}
