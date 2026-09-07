'use client';

import { useEffect, useState, useRef, useCallback } from 'react';

// ═══════════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════════

export interface PriceUpdate {
  symbol: string;
  symbol_formatted: string;
  price: number;
  bid?: number;
  ask?: number;
  high_24h?: number;
  low_24h?: number;
  volume_24h?: number;
  change_24h?: number;
  instant_change: number;
  direction: 'up' | 'down' | 'none';
  timestamp: string;
}

export interface PriceState {
  [symbol: string]: {
    price: number;
    change_24h: number;
    direction: 'up' | 'down' | 'none';
    lastUpdate: number;
    flashClass: string;
  };
}

interface UseWebSocketPricesOptions {
  enabled?: boolean;
  onPriceUpdate?: (update: PriceUpdate) => void;
  reconnectInterval?: number;
  pingInterval?: number;
}

// ═══════════════════════════════════════════════════════════════════════════════
// WEBSOCKET HOOK
// ═══════════════════════════════════════════════════════════════════════════════

export function useWebSocketPrices(options: UseWebSocketPricesOptions = {}) {
  const { enabled = true, onPriceUpdate, reconnectInterval = 5000, pingInterval = 30000 } = options;

  const [prices, setPrices] = useState<PriceState>({});
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Clear flash class after animation
  const clearFlash = useCallback((symbol: string) => {
    setTimeout(() => {
      setPrices((prev) => ({
        ...prev,
        [symbol]: {
          ...prev[symbol],
          flashClass: '',
        },
      }));
    }, 500); // Match animation duration
  }, []);

  // Handle price update message
  const handlePriceUpdate = useCallback(
    (update: PriceUpdate) => {
      const symbol = update.symbol.replace('USDT', ''); // BTCUSDT -> BTC

      setPrices((prev) => {
        const prevPrice = prev[symbol]?.price || 0;
        const newPrice = update.price;

        // Determine flash class based on price change
        let flashClass = '';
        if (prevPrice > 0 && newPrice !== prevPrice) {
          flashClass = newPrice > prevPrice ? 'price-flash-up' : 'price-flash-down';
        }

        return {
          ...prev,
          [symbol]: {
            price: newPrice,
            change_24h: update.change_24h || 0,
            direction: update.direction,
            lastUpdate: Date.now(),
            flashClass,
          },
        };
      });

      // Clear flash after animation
      clearFlash(symbol);

      // Call callback if provided
      if (onPriceUpdate) {
        onPriceUpdate(update);
      }
    },
    [clearFlash, onPriceUpdate]
  );

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (!enabled) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/prices';
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('🔌 WebSocket connected');
        setIsConnected(true);
        setError(null);

        // Start ping interval
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, pingInterval);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'price_update') {
            handlePriceUpdate(data as PriceUpdate);
          } else if (data.type === 'snapshot') {
            // Handle initial snapshot
            console.log('📸 Received price snapshot:', Object.keys(data.prices).length, 'symbols');
          }
        } catch (e) {
          // Ignore pong responses
          if (event.data !== 'pong') {
            console.error('Failed to parse WebSocket message:', e);
          }
        }
      };

      ws.onerror = (event) => {
        console.error('WebSocket error:', event);
        setError('WebSocket connection error');
      };

      ws.onclose = () => {
        console.log('🔌 WebSocket disconnected');
        setIsConnected(false);

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }

        // Schedule reconnect
        if (enabled) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log('🔄 Attempting to reconnect...');
            connect();
          }, reconnectInterval);
        }
      };
    } catch (e) {
      console.error('Failed to connect WebSocket:', e);
      setError('Failed to connect');
    }
  }, [enabled, handlePriceUpdate, pingInterval, reconnectInterval]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    if (enabled) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [enabled, connect, disconnect]);

  // Get price for a specific symbol
  const getPrice = useCallback(
    (symbol: string) => {
      const normalizedSymbol = symbol.replace('USDT', '').replace('/', '').toUpperCase();
      return prices[normalizedSymbol];
    },
    [prices]
  );

  return {
    prices,
    isConnected,
    error,
    connect,
    disconnect,
    getPrice,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// CSS STYLES (add to your global CSS or component)
// ═══════════════════════════════════════════════════════════════════════════════
/*
Add these to your globals.css:

@keyframes flash-green {
    0% { background-color: rgba(34, 197, 94, 0.4); }
    100% { background-color: transparent; }
}

@keyframes flash-red {
    0% { background-color: rgba(239, 68, 68, 0.4); }
    100% { background-color: transparent; }
}

.price-flash-up {
    animation: flash-green 0.5s ease-out;
}

.price-flash-down {
    animation: flash-red 0.5s ease-out;
}
*/

export default useWebSocketPrices;
