'use client';

import { useState, useMemo, useEffect } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { useStore, NewsItem } from '@/store/useStore';
import AssetTag from '@/components/ui/AssetTag';
import { assetClassOf, ASSET_CLASS_LABEL } from '@/lib/asset-class';
import { useNews, useStartNewsAnalysis } from '@/hooks/queries';
import { Newspaper, TrendingUp, Bitcoin, Clock, RefreshCw, Filter } from 'lucide-react';

type NewsFilter = 'all' | 'stock' | 'crypto';

const FILTERS: { value: NewsFilter; label: string; icon: typeof Filter }[] = [
  { value: 'all', label: 'All', icon: Filter },
  { value: 'stock', label: 'Stocks', icon: TrendingUp },
  { value: 'crypto', label: 'Crypto', icon: Bitcoin },
];

export default function NewsFeed() {
  const { selectedNews, setNewsItems, selectNews, setAnalysisJobId } = useStore();
  const startAnalysis = useStartNewsAnalysis();

  const [activeFilter, setActiveFilter] = useState<NewsFilter>('all');

  // React Query — auto-refresh every 30s
  const { data: rawItems, isLoading: isLoadingNews, refetch } = useNews(undefined);

  // Sort once when raw data changes, sync to store
  const sortedItems = useMemo(() => {
    if (!rawItems) return [];
    return [...rawItems].sort((a, b) => {
      const dateCompare = b.published_at.localeCompare(a.published_at);
      if (dateCompare !== 0) return dateCompare;
      return a.id.localeCompare(b.id);
    });
  }, [rawItems]);

  // Sync sorted items to store (effect, not memo side-effect)
  useEffect(() => {
    if (sortedItems.length > 0) setNewsItems(sortedItems);
  }, [sortedItems, setNewsItems]);

  // Filter in derived state
  const filteredNews = useMemo(() => {
    if (activeFilter === 'all') return sortedItems;
    return sortedItems.filter((news) => news.asset_type === activeFilter);
  }, [sortedItems, activeFilter]);

  const handleNewsClick = (news: NewsItem) => {
    selectNews(news);

    // Fire-and-forget: the panel subscribes to the analysis by news id, so the
    // result lands wherever it belongs even if the user has moved on. The price
    // is resolved server-side now — fetching it here serialised a second
    // round-trip and swallowed its errors.
    startAnalysis.mutate(
      { newsId: news.id },
      { onSuccess: (job) => setAnalysisJobId(news.id, job.jobId) }
    );
  };

  const formatTime = (dateString: string) =>
    formatDistanceToNow(new Date(dateString), { addSuffix: true });

  return (
    <div className="flex flex-col h-full">
      {/* Header - Fixed height to align with other panels */}
      <div className="h-10 shrink-0 px-4 border-b border-line flex items-center justify-between bg-surface">
        <div className="flex items-center gap-2">
          <Newspaper className="w-3.5 h-3.5 text-fg-muted" />
          <h2 className="text-base font-semibold text-fg">Feed</h2>
        </div>
        <button
          onClick={() => refetch()}
          aria-label="Refresh news"
          className="p-1.5 rounded-md text-fg-muted hover:text-fg hover:bg-surface-2 transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoadingNews ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Filter Tabs */}
      <div className="shrink-0 px-3 py-2 border-b border-line flex gap-1">
        {FILTERS.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            onClick={() => setActiveFilter(value)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-sm transition-colors ${
              activeFilter === value ? 'bg-surface-2 text-fg' : 'text-fg-muted hover:text-fg'
            }`}
          >
            <Icon className="w-3 h-3" />
            {label}
          </button>
        ))}
      </div>

      {/* News List */}
      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        {isLoadingNews ? (
          // Loading skeleton
          <div className="p-3 space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="p-3 rounded-lg border border-line">
                <div className="h-3 w-3/4 shimmer rounded mb-2"></div>
                <div className="h-2.5 w-full shimmer rounded mb-2"></div>
                <div className="h-2.5 w-1/2 shimmer rounded"></div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-3 space-y-1.5">
            {filteredNews.map((news) => (
              <article
                key={news.id}
                role="button"
                tabIndex={0}
                onClick={() => handleNewsClick(news)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleNewsClick(news);
                  }
                }}
                data-asset={assetClassOf(news)}
                title={ASSET_CLASS_LABEL[assetClassOf(news)]}
                className={`news-item p-3 rounded-lg border cursor-pointer ${
                  selectedNews?.id === news.id ? 'selected border-accent' : 'border-line'
                }`}
              >
                <div className="flex items-center gap-2 mb-1.5">
                  <AssetTag symbol={news.symbol} />
                  <span className="flex items-center gap-1 text-xs text-fg-subtle">
                    <Clock className="w-2.5 h-2.5" />
                    {formatTime(news.published_at)}
                  </span>
                </div>

                <h3 className="text-base text-fg leading-snug mb-1">{news.title}</h3>

                <p className="text-sm text-fg-muted line-clamp-2">{news.summary}</p>

                <div className="mt-1.5 text-xs text-fg-subtle">{news.source}</div>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
