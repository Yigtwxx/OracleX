'use client';

import { useState, useMemo } from 'react';
import { Search, Plus, Check } from 'lucide-react';
import { useMarketOverview, useNasdaqOverview } from '@/hooks/queries';
import Modal from '@/components/ui/Modal';
import type { CoinData } from '@/lib/api';

interface Asset {
  symbol: string;
  name: string;
  type: 'STOCK' | 'CRYPTO';
  logo?: string;
}

interface CreateWatchlistModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (name: string, items: { symbol: string; type: 'STOCK' | 'CRYPTO' }[]) => void;
}

export default function CreateWatchlistModal({
  isOpen,
  onClose,
  onCreate,
}: CreateWatchlistModalProps) {
  const [name, setName] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedAssets, setSelectedAssets] = useState<Asset[]>([]);

  // React Query hooks — share cache with Overview/other pages
  const { data: cryptoData, isLoading: isLoadingCrypto } = useMarketOverview(isOpen);
  const { data: stockData, isLoading: isLoadingStocks } = useNasdaqOverview(isOpen);

  const isLoading = isLoadingCrypto || isLoadingStocks;

  // Derive available assets from React Query data
  const availableAssets = useMemo(() => {
    const assets: Asset[] = [];

    if (cryptoData?.coins) {
      cryptoData.coins.forEach((c: CoinData) => {
        assets.push({ symbol: c.symbol, name: c.name, type: 'CRYPTO', logo: c.logo });
      });
    }

    if (stockData?.coins) {
      stockData.coins.forEach((s: CoinData) => {
        assets.push({ symbol: s.symbol, name: s.name, type: 'STOCK', logo: s.logo });
      });
    }

    return assets;
  }, [cryptoData, stockData]);

  const toggleAsset = (asset: Asset) => {
    if (selectedAssets.find((a) => a.symbol === asset.symbol)) {
      setSelectedAssets((prev) => prev.filter((a) => a.symbol !== asset.symbol));
    } else {
      setSelectedAssets((prev) => [...prev, asset]);
    }
  };

  const handleCreate = () => {
    if (!name.trim()) return;
    const items = selectedAssets.map((a) => ({
      symbol: a.symbol,
      type: a.type,
    }));
    onCreate(name, items);
    // Reset
    setName('');
    setSelectedAssets([]);
    onClose();
  };

  if (!isOpen) return null;

  const filteredAssets = availableAssets.filter(
    (a) =>
      a.symbol.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="New Watchlist">
      <div>
        <div className="p-4 space-y-4">
          {/* Name Input */}
          <div>
            <label className="label block mb-1.5">Watchlist Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., My Portfolio"
              className="w-full bg-surface-2 border border-line rounded-md px-2.5 py-1.5 text-base text-fg placeholder:text-fg-subtle focus:outline-none focus:border-accent transition-colors"
            />
          </div>

          {/* Search */}
          <div>
            <label className="label block mb-1.5">Add Assets ({selectedAssets.length})</label>
            <div className="relative mb-2">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-fg-subtle" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search stocks or crypto…"
                className="w-full bg-surface-2 border border-line rounded-md pl-8 pr-2.5 py-1.5 text-base text-fg placeholder:text-fg-subtle focus:outline-none focus:border-accent transition-colors"
              />
            </div>

            {/* List */}
            <div className="h-48 overflow-y-auto overflow-x-hidden custom-scrollbar border border-line rounded-md">
              {isLoading ? (
                <div className="flex items-center justify-center h-full text-fg-subtle text-base">
                  Loading assets…
                </div>
              ) : (
                <div className="divide-y divide-line">
                  {filteredAssets.map((asset) => {
                    const isSelected = !!selectedAssets.find((a) => a.symbol === asset.symbol);
                    return (
                      <button
                        key={`${asset.type}-${asset.symbol}`}
                        onClick={() => toggleAsset(asset)}
                        className={`w-full flex items-center justify-between p-2.5 hover:bg-surface-2 transition-colors text-left ${isSelected ? 'bg-surface-2' : ''}`}
                      >
                        <div className="flex items-center gap-3">
                          {asset.logo ? (
                            <img
                              src={asset.logo}
                              alt={asset.symbol}
                              className="w-5 h-5 rounded-full"
                            />
                          ) : (
                            <div className="w-5 h-5 rounded-full bg-surface-2" />
                          )}
                          <div>
                            <div className="text-base text-fg">{asset.symbol}</div>
                            <div className="text-fg-subtle text-xs truncate max-w-[200px]">
                              {asset.name}
                            </div>
                          </div>
                        </div>
                        {isSelected ? (
                          <Check className="w-3.5 h-3.5 text-accent" />
                        ) : (
                          <Plus className="w-3.5 h-3.5 text-fg-subtle" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-line flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-md text-base text-fg-muted hover:text-fg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!name.trim() || selectedAssets.length === 0}
            className="px-3 py-1.5 rounded-md text-base bg-accent text-white hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Create Watchlist
          </button>
        </div>
      </div>
    </Modal>
  );
}
