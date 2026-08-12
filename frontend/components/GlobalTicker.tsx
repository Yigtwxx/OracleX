'use client';

import React, { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface MarketIndex {
  symbol: string;
  name: string;
  price: number;
  change_24h: number;
  region: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function GlobalTicker() {
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchIndices = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/market/indices`);
        if (res.ok) {
          const data = await res.json();
          setIndices(data);
        }
      } catch (error) {
        console.error('Failed to fetch indices', error);
      } finally {
        setLoading(false);
      }
    };

    fetchIndices();
    // Refresh every 5 minutes
    const interval = setInterval(fetchIndices, 300000);
    return () => clearInterval(interval);
  }, []);

  if (loading || indices.length === 0) return null;

  // Duplicate list for seamless infinite scroll
  const tickerItems = [...indices, ...indices, ...indices];

  return (
    <div className="h-8 shrink-0 bg-bg border-b border-line flex items-center relative overflow-hidden z-40">
      {/* Label */}
      <div className="absolute left-0 top-0 bottom-0 bg-bg px-3 flex items-center z-10 border-r border-line">
        <span className="label">Global Markets</span>
      </div>

      {/* Scrolling Ticker */}
      <div className="flex items-center overflow-hidden w-full mask-linear-fade">
        <div className="flex animate-ticker whitespace-nowrap pl-48 hover:pause-animation">
          {tickerItems.map((item, index) => (
            <div
              key={`${item.symbol}-${index}`}
              className="flex items-center gap-2 px-5 border-r border-line"
            >
              <span className="text-xs text-fg-muted">{item.name}</span>
              <span className="text-xs font-mono tabnum text-fg">
                {item.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
              </span>
              <span
                className={`flex items-center gap-0.5 text-2xs font-mono tabnum ${item.change_24h >= 0 ? 'text-up' : 'text-down'}`}
              >
                {item.change_24h >= 0 ? (
                  <TrendingUp className="w-3 h-3" />
                ) : (
                  <TrendingDown className="w-3 h-3" />
                )}
                {Math.abs(item.change_24h).toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      <style jsx>{`
        .animate-ticker {
          animation: ticker 40s linear infinite;
        }
        .hover\\:pause-animation:hover {
          animation-play-state: paused;
        }
        .mask-linear-fade {
          mask-image: linear-gradient(
            to right,
            transparent 0%,
            black 200px,
            black calc(100% - 24px),
            transparent 100%
          );
        }
        @keyframes ticker {
          0% {
            transform: translateX(0);
          }
          100% {
            transform: translateX(-33.33%);
          } /* Move by 1/3 since we tripled the list */
        }
      `}</style>
    </div>
  );
}
