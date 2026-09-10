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
    /**
     * Null for a row seeded from the connect-time snapshot, which carries a
     * price and nothing else. Not zero: a snapshot says "this is the last
     * price we saw", not "this asset is flat on the day".
     */
    change_24h: number | null;
    direction: 'up' | 'down' | 'none';
    lastUpdate: number;
    flashClass: string;
  };
}

/**
 * The one place a wire symbol becomes a key in `PriceState`.
 *
 * The two messages that reach this hook are keyed differently, and that is not
 * a detail either side is going to change: `price_update` carries the pair
 * with the slash already stripped (`BTCUSDT`), while the snapshot is a copy of
 * the streamer's own cache, which is keyed by the ccxt market symbol the
 * exchange is subscribed with (`BTC/USDT`). Feeding the second through a
 * normaliser written for the first stores `BTCUSDT` beside `BTC` and every
 * lookup misses — silently, since a missing key here just means "no live
 * price" and falls back to the REST value.
 *
 * `AssetTable` had its own third spelling of this, applying the same two
 * replacements in the other order. One exported function instead, so a lookup
 * cannot disagree with a write.
 *
 * The quote suffix is anchored: an unanchored `replace('USDT', '')` would eat
 * the first occurrence wherever it fell.
 */
export function normalizePriceSymbol(symbol: string): string {
  return symbol.replace('/', '').toUpperCase().replace(/USDT$/, '');
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
  // Whether the socket that is closing was closed by us rather than by the
  // network. Closing one that is still CONNECTING is "failing the connection"
  // per the WebSocket spec, which fires `error` before `close` — and StrictMode
  // does exactly that on every dev mount, so the discarded socket reported an
  // empty `WebSocket error: {}` through the Next.js overlay for a connection
  // nobody was waiting on. The same flag keeps that socket's `close`, which is
  // delivered after the effect cleanup has already run, from scheduling a
  // reconnect: the timer outlived the effect and reopened a connection no page
  // was reading, which is why the server counted clients no tab had.
  const intentionalCloseRef = useRef(false);

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
      const symbol = normalizePriceSymbol(update.symbol); // BTCUSDT -> BTC

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

  /**
   * Seed from the snapshot the server sends on connect.
   *
   * The backend has always sent this — `routers/websocket.py` writes the
   * streamer's cache down the socket before its loop starts — and the handler
   * here logged the symbol count and threw it away. The cost was invisible
   * because there is a fallback: until the first per-symbol tick arrives for a
   * row, the table renders the REST price, so the board looked populated while
   * being as stale as the last overview fetch. On a quiet pair that is minutes.
   *
   * No flash on any of these. A flash means "this just moved"; a snapshot is
   * the state that was already true when the socket opened, and animating it
   * would report a market's worth of movement that nobody's connect caused.
   *
   * A live update that beat the snapshot in wins. That ordering is real — the
   * server writes the snapshot before entering its broadcast loop, but nothing
   * makes the two atomic — and it matters because the update carries a
   * direction and a 24h change the snapshot does not.
   */
  const handleSnapshot = useCallback((snapshot: Record<string, number>) => {
    const now = Date.now();
    setPrices((prev) => {
      const next = { ...prev };
      for (const [wireSymbol, price] of Object.entries(snapshot)) {
        if (typeof price !== 'number' || !Number.isFinite(price)) continue;
        const symbol = normalizePriceSymbol(wireSymbol);
        if (next[symbol]) continue;
        next[symbol] = {
          price,
          change_24h: null,
          direction: 'none',
          lastUpdate: now,
          flashClass: '',
        };
      }
      return next;
    });
  }, []);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (!enabled) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/prices';
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      intentionalCloseRef.current = false;

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
          } else if (data.type === 'snapshot' && data.prices) {
            handleSnapshot(data.prices as Record<string, number>);
          }
        } catch (e) {
          // Ignore pong responses
          if (event.data !== 'pong') {
            console.error('Failed to parse WebSocket message:', e);
          }
        }
      };

      ws.onerror = (event) => {
        // A socket we replaced or closed ourselves is not a failure to report.
        if (wsRef.current !== ws || intentionalCloseRef.current) return;
        console.error('WebSocket error:', event);
        setError('WebSocket connection error');
      };

      ws.onclose = () => {
        // Only the live socket owns the shared state and the timers; a stale
        // one closing must not clear the current connection's ping interval.
        if (wsRef.current !== ws) return;
        wsRef.current = null;

        console.log('🔌 WebSocket disconnected');
        setIsConnected(false);

        // Clear ping interval
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }

        // Schedule reconnect
        if (enabled && !intentionalCloseRef.current) {
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
  }, [enabled, handlePriceUpdate, handleSnapshot, pingInterval, reconnectInterval]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
    if (wsRef.current) {
      // Cleared before close() so the close event, which arrives after this
      // cleanup, sees no live socket and neither reconnects nor logs.
      const ws = wsRef.current;
      wsRef.current = null;
      ws.close();
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
  const getPrice = useCallback((symbol: string) => prices[normalizePriceSymbol(symbol)], [prices]);

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
