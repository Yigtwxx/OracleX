'use client';

import { useState } from 'react';
import { Plus, Trash2, Eye, AlertTriangle } from 'lucide-react';
import { useWatchlists, useCreateWatchlist, useDeleteWatchlist } from '@/hooks/queries';
import { useOptionalAuth } from '@/contexts/AuthContext';
import CreateWatchlistModal from './CreateWatchlistModal';

export default function WatchlistWidget() {
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);

  const { user } = useOptionalAuth();
  const { data: watchlists = [], isLoading, isError, refetch } = useWatchlists();
  const createMutation = useCreateWatchlist();
  const deleteMutation = useDeleteWatchlist();

  const handleCreate = async (
    name: string,
    items: { symbol: string; type: 'STOCK' | 'CRYPTO' }[]
  ) => {
    try {
      await createMutation.mutateAsync({ name, items });
    } catch (error) {
      console.error(error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this watchlist?')) return;
    try {
      await deleteMutation.mutateAsync(id);
    } catch (error) {
      console.error(error);
    }
  };

  const isBusy = isLoading || createMutation.isPending;

  // Watchlists are per account now — they used to be one shared file behind
  // three unauthenticated endpoints, which meant every visitor saw and could
  // delete everyone else's. A signed-out visitor is told why the panel is
  // empty rather than shown an empty list or a failed request.
  if (!user) {
    return (
      <section>
        <h2 className="text-md font-semibold text-fg mb-3">Your Watchlists</h2>
        <div className="surface p-8 text-center">
          <Eye className="w-5 h-5 mx-auto mb-3 text-fg-subtle" />
          <h3 className="text-base text-fg mb-1">Sign in to keep a watchlist</h3>
          <p className="text-base text-fg-subtle">
            Watchlists are saved to your account, so they follow you between devices.
          </p>
        </div>
      </section>
    );
  }

  if (isBusy && watchlists.length === 0) {
    return <div className="surface h-40 shimmer" />;
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-md font-semibold text-fg">Your Watchlists</h2>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1 bg-surface border border-line rounded-md text-sm text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          New List
        </button>
      </div>

      {/* A failed request is not an empty account — offering "create your first
          watchlist" here would hide the outage and risk a confusing duplicate. */}
      {isError ? (
        <div className="surface p-8 text-center">
          <AlertTriangle className="w-5 h-5 mx-auto mb-3 text-fg-subtle" />
          <h3 className="text-base text-fg mb-1">Watchlists unavailable</h3>
          <p className="text-base text-fg-subtle mb-4">
            Could not load your watchlists. Your saved lists are unaffected.
          </p>
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 bg-surface border border-line rounded-md text-base text-fg-muted hover:text-fg hover:border-line-strong transition-colors"
          >
            Retry
          </button>
        </div>
      ) : watchlists.length === 0 ? (
        <div className="surface p-8 text-center">
          <Eye className="w-5 h-5 mx-auto mb-3 text-fg-subtle" />
          <h3 className="text-base text-fg mb-1">No watchlists yet</h3>
          <p className="text-base text-fg-subtle mb-4">
            Create a watchlist to track your favorite stocks and crypto assets.
          </p>
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="px-3 py-1.5 bg-accent text-white text-base rounded-md hover:opacity-90 transition-opacity"
          >
            Create Watchlist
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {watchlists.map((list) => (
            <div key={list.id} className="surface flex flex-col">
              <div className="flex items-center justify-between px-4 h-10 border-b border-line">
                <h3 className="text-base font-semibold text-fg">{list.name}</h3>
                <button
                  onClick={() => handleDelete(list.id)}
                  aria-label={`Delete watchlist ${list.name}`}
                  className="p-1 text-fg-subtle hover:text-down rounded transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="divide-y divide-line overflow-y-auto overflow-x-hidden custom-scrollbar max-h-[300px]">
                {list.items.map((item, idx) => {
                  // A missing quote is unknown, not zero. Defaulting to 0 here
                  // rendered unresolved symbols as "$0.00" with a green "+0.00%".
                  const { price, change_24h: change } = item;
                  return (
                    <div
                      key={`${item.symbol}-${idx}`}
                      className="flex items-center justify-between gap-2 px-4 py-2 hover:bg-surface-2 transition-colors"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        {item.logo ? (
                          <img src={item.logo} alt="" className="w-5 h-5 rounded-full shrink-0" />
                        ) : (
                          <div className="w-5 h-5 rounded-full bg-surface-2 flex items-center justify-center text-2xs text-fg-subtle shrink-0">
                            {item.symbol[0]}
                          </div>
                        )}
                        <div className="min-w-0">
                          <div className="text-base text-fg truncate">{item.symbol}</div>
                          <div className="text-2xs text-fg-subtle">{item.type}</div>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        <div
                          className={`text-base font-mono tabnum ${price === null ? 'text-fg-subtle' : 'text-fg'}`}
                        >
                          {price === null
                            ? '—'
                            : `$${price.toLocaleString('en-US', {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: price < 1 ? 4 : 2,
                              })}`}
                        </div>
                        {change === null ? (
                          <div className="text-xs font-mono tabnum text-fg-subtle">—</div>
                        ) : (
                          <div
                            className={`text-xs font-mono tabnum ${change >= 0 ? 'text-up' : 'text-down'}`}
                          >
                            {change >= 0 ? '+' : '−'}
                            {Math.abs(change).toFixed(2)}%
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      <CreateWatchlistModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onCreate={handleCreate}
      />
    </section>
  );
}
