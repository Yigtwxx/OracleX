'use client';

import { useState } from 'react';
import { useStore } from '@/store/useStore';
import { Bell, Trash2, TrendingUp, TrendingDown, Plus } from 'lucide-react';
import Modal from '@/components/ui/Modal';

export default function PriceAlertModal() {
  const { chartSymbol, isAlertModalOpen, toggleAlertModal, priceAlerts, addAlert, removeAlert } =
    useStore();

  const [targetPrice, setTargetPrice] = useState('');
  const [condition, setCondition] = useState<'above' | 'below'>('above');

  const displaySymbol = chartSymbol.includes(':') ? chartSymbol.split(':')[1] : chartSymbol;

  const handleAddAlert = () => {
    const price = parseFloat(targetPrice);
    if (isNaN(price) || price <= 0) return;

    addAlert({
      symbol: chartSymbol,
      displaySymbol,
      targetPrice: price,
      condition,
    });

    setTargetPrice('');

    // Request notification permission if not granted
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  };

  if (!isAlertModalOpen) return null;

  // Alerts for current symbol
  const currentSymbolAlerts = priceAlerts.filter((a) => a.symbol === chartSymbol);
  // Alerts for other symbols
  const otherAlerts = priceAlerts.filter((a) => a.symbol !== chartSymbol);
  const activeAlerts = priceAlerts.filter((a) => a.isActive);

  const AlertItem = ({ alert }: { alert: (typeof priceAlerts)[0] }) => (
    <div
      className={`flex items-center justify-between p-3 rounded-lg border ${
        alert.isTriggered ? 'bg-warn-bg border-warn' : 'bg-surface border-line'
      }`}
    >
      <div className="flex items-center gap-3">
        <div
          className={`w-8 h-8 rounded-lg flex items-center justify-center ${
            alert.condition === 'above' ? 'bg-up-bg' : 'bg-down-bg'
          }`}
        >
          {alert.condition === 'above' ? (
            <TrendingUp className="w-4 h-4 text-up" />
          ) : (
            <TrendingDown className="w-4 h-4 text-down" />
          )}
        </div>
        <div>
          <p className="text-base text-fg">
            {alert.displaySymbol} <span className="text-fg-subtle">→</span> $
            {alert.targetPrice.toLocaleString()}
          </p>
          <p className="text-xs text-fg-subtle">
            {alert.isTriggered
              ? 'Triggered'
              : `${alert.condition === 'above' ? 'Above' : 'Below'} target`}
          </p>
        </div>
      </div>
      <button
        onClick={() => removeAlert(alert.id)}
        className="p-2 rounded-lg hover:bg-down-bg transition-colors group"
      >
        <Trash2 className="w-4 h-4 text-fg-subtle group-hover:text-down" />
      </button>
    </div>
  );

  return (
    <Modal isOpen onClose={() => toggleAlertModal(false)} title="Price Alerts" maxWidth="max-w-md">
      <div>
        {/* Add Alert Form */}
        <div className="p-4 border-b border-line">
          <div className="flex gap-2">
            {/* Condition Toggle */}
            <div className="flex rounded-lg border border-line overflow-hidden">
              <button
                onClick={() => setCondition('above')}
                className={`px-2.5 py-1.5 text-base transition-colors flex items-center gap-1 ${
                  condition === 'above' ? 'bg-up-bg text-up' : 'text-fg-muted hover:bg-surface-2'
                }`}
              >
                <TrendingUp className="w-3.5 h-3.5" />
                Above
              </button>
              <button
                onClick={() => setCondition('below')}
                className={`px-2.5 py-1.5 text-base transition-colors flex items-center gap-1 ${
                  condition === 'below'
                    ? 'bg-down-bg text-down'
                    : 'text-fg-muted hover:bg-surface-2'
                }`}
              >
                <TrendingDown className="w-3.5 h-3.5" />
                Below
              </button>
            </div>

            {/* Price Input */}
            <div className="flex-1 relative">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-base text-fg-subtle">
                $
              </span>
              <input
                type="number"
                value={targetPrice}
                onChange={(e) => setTargetPrice(e.target.value)}
                placeholder="Target price"
                className="w-full pl-6 pr-2.5 py-1.5 bg-surface-2 border border-line rounded-md text-base text-fg font-mono tabnum placeholder:text-fg-subtle placeholder:font-sans focus:outline-none focus:border-accent"
              />
            </div>

            {/* Add Button */}
            <button
              onClick={handleAddAlert}
              disabled={!targetPrice || parseFloat(targetPrice) <= 0}
              className="px-3 py-1.5 bg-accent text-white text-base rounded-md hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
            >
              <Plus className="w-3.5 h-3.5" />
              Add
            </button>
          </div>
        </div>

        {/* All Alerts List */}
        <div className="p-4 max-h-80 overflow-y-auto">
          {priceAlerts.length === 0 ? (
            <div className="text-center py-8">
              <Bell className="w-5 h-5 text-fg-subtle mx-auto mb-3" />
              <p className="text-base text-fg-muted">No alerts yet</p>
              <p className="text-xs text-fg-subtle mt-1">Add an alert above</p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Current Symbol Alerts */}
              {currentSymbolAlerts.length > 0 && (
                <div>
                  <p className="label mb-2">{displaySymbol}</p>
                  <div className="space-y-2">
                    {currentSymbolAlerts.map((alert) => (
                      <AlertItem key={alert.id} alert={alert} />
                    ))}
                  </div>
                </div>
              )}

              {/* Other Alerts */}
              {otherAlerts.length > 0 && (
                <div>
                  <p className="label mb-2 mt-4">Other Alerts</p>
                  <div className="space-y-2">
                    {otherAlerts.map((alert) => (
                      <AlertItem key={alert.id} alert={alert} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {activeAlerts.length > 0 && (
          <div className="p-4 border-t border-line">
            <p className="text-xs text-fg-subtle text-center">
              <span className="tabnum">{activeAlerts.length}</span> active alert
              {activeAlerts.length > 1 ? 's' : ''} · checked every 10s · sound on
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}
