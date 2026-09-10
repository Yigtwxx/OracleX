import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizePriceSymbol, useWebSocketPrices } from './useWebSocketPrices';

/**
 * The lifecycle, and the two wire formats that reach it.
 *
 * Every bug this file guards against was a socket the page had already given
 * up on still being treated as the live one. They are invisible in a browser
 * except as noise — an empty `WebSocket error: {}` in the dev overlay, a
 * connection count higher than the number of open tabs — so they are exactly
 * the kind that survives a refactor unless something asserts them.
 *
 * The fake socket below delivers `close` only when a test asks it to, because
 * the ordering *is* the subject: a browser fires it after the effect cleanup
 * has returned, and a fake that fires it inline would test a sequence that
 * never happens.
 */

type Handler = ((event: Event) => void) | null;

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: FakeWebSocket[] = [];

  readyState: number = FakeWebSocket.CONNECTING;
  sent: string[] = [];

  onopen: Handler = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: Handler = null;
  onclose: Handler = null;

  /** Set by close(); the events wait here until a test delivers them. */
  private closePending = false;
  /** Closing a socket that never opened "fails" it: error precedes close. */
  private closeFailed = false;

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.closeFailed = this.readyState === FakeWebSocket.CONNECTING;
    this.closePending = true;
    this.readyState = FakeWebSocket.CLOSING;
  }

  // ── test controls ─────────────────────────────────────────────────────────

  accept(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  /** Flush the events a browser would have queued when close() was called. */
  deliverClose(): void {
    if (!this.closePending) return;
    this.closePending = false;
    this.readyState = FakeWebSocket.CLOSED;
    if (this.closeFailed) this.onerror?.(new Event('error'));
    this.onclose?.(new Event('close'));
  }

  /** Hand the hook a server message. */
  deliver(payload: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }));
  }

  /** The other kind of close: the connection dropped on its own. */
  drop(): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.onerror?.(new Event('error'));
    this.onclose?.(new Event('close'));
  }
}

const RECONNECT_INTERVAL = 5000;
const PING_INTERVAL = 30000;

function render(options: { strict?: boolean } = {}) {
  return renderHook(
    () =>
      useWebSocketPrices({
        reconnectInterval: RECONNECT_INTERVAL,
        pingInterval: PING_INTERVAL,
      }),
    options.strict ? { wrapper: StrictMode } : undefined
  );
}

let errorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', FakeWebSocket);
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'log').mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useWebSocketPrices', () => {
  it('does not report the socket StrictMode discards before it opened', () => {
    const { result } = render({ strict: true });

    // Mount, cleanup, mount again: the first socket is closed mid-handshake.
    const [discarded, live] = FakeWebSocket.instances;
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      discarded.deliverClose();
    });

    expect(errorSpy).not.toHaveBeenCalled();
    expect(result.current.error).toBeNull();

    // And it must not have queued a reconnect on the way out.
    act(() => {
      vi.advanceTimersByTime(RECONNECT_INTERVAL * 2);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      live.accept();
    });
    expect(result.current.isConnected).toBe(true);
  });

  it('leaves the live connection ping when a discarded socket closes late', () => {
    render({ strict: true });
    const [discarded, live] = FakeWebSocket.instances;

    act(() => {
      live.accept();
    });
    act(() => {
      discarded.deliverClose();
    });

    act(() => {
      vi.advanceTimersByTime(PING_INTERVAL);
    });
    expect(live.sent).toEqual(['ping']);
  });

  it('closes on unmount and stays closed', () => {
    const { result, unmount } = render();
    const [socket] = FakeWebSocket.instances;

    act(() => {
      socket.accept();
    });
    expect(result.current.isConnected).toBe(true);

    unmount();
    expect(socket.readyState).toBe(FakeWebSocket.CLOSING);

    // The close event arrives after the cleanup has already run; nothing about
    // it may resurrect the connection for a page that is gone.
    act(() => {
      socket.deliverClose();
      vi.advanceTimersByTime(RECONNECT_INTERVAL * 2);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it('reports a genuine drop and reconnects', () => {
    const { result } = render();
    const [socket] = FakeWebSocket.instances;

    act(() => {
      socket.accept();
    });
    act(() => {
      socket.drop();
    });

    expect(errorSpy).toHaveBeenCalled();
    expect(result.current.error).toBe('WebSocket connection error');
    expect(result.current.isConnected).toBe(false);

    act(() => {
      vi.advanceTimersByTime(RECONNECT_INTERVAL);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    act(() => {
      FakeWebSocket.instances[1].accept();
    });
    expect(result.current.isConnected).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it('keys prices by the bare symbol', () => {
    const { result } = render();
    const [socket] = FakeWebSocket.instances;

    act(() => {
      socket.accept();
      socket.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'price_update',
            symbol: 'BTCUSDT',
            price: 64000,
            change_24h: 1.5,
            direction: 'up',
          }),
        })
      );
    });

    expect(result.current.getPrice('BTC/USDT')?.price).toBe(64000);
    expect(result.current.prices.BTC.direction).toBe('up');
  });
});

/**
 * The connect-time snapshot, which was parsed and dropped.
 *
 * `routers/websocket.py` writes the streamer's price cache down the socket
 * before its broadcast loop starts, and the handler here logged the symbol
 * count and did nothing else. Nothing broke visibly, because the table falls
 * back to the REST price until a per-symbol tick arrives — so the board was
 * quietly as stale as the last overview fetch instead of as fresh as the
 * socket.
 *
 * The keys are the trap. That cache is keyed by the ccxt market symbol the
 * exchange is subscribed with (`BTC/USDT`), while `price_update` has already
 * stripped the slash (`BTCUSDT`). Applying the update path's normaliser to
 * snapshot keys stores rows nothing ever looks up, and a missing key here is
 * indistinguishable from "no live price yet".
 */
describe('useWebSocketPrices snapshot', () => {
  function connected() {
    const rendered = render();
    const [socket] = FakeWebSocket.instances;
    act(() => {
      socket.accept();
    });
    return { ...rendered, socket };
  }

  it('seeds prices from the snapshot', () => {
    const { result, socket } = connected();

    act(() => {
      socket.deliver({ type: 'snapshot', prices: { 'BTC/USDT': 64000, 'ETH/USDT': 3200 } });
    });

    expect(result.current.prices.BTC.price).toBe(64000);
    expect(result.current.prices.ETH.price).toBe(3200);
  });

  it('keys the snapshot the same way an update is keyed', () => {
    // The regression. Both wire spellings of the same pair must land on one
    // key, or the lookup that reads the update path misses every snapshot row.
    const { result, socket } = connected();

    act(() => {
      socket.deliver({ type: 'snapshot', prices: { 'BTC/USDT': 64000 } });
    });

    expect(Object.keys(result.current.prices)).toEqual(['BTC']);
    expect(result.current.getPrice('BTCUSDT')?.price).toBe(64000);
  });

  it('does not flash a snapshot', () => {
    // A flash means "this just moved". The snapshot is the state that was
    // already true when the socket opened.
    const { result, socket } = connected();

    act(() => {
      socket.deliver({ type: 'snapshot', prices: { 'BTC/USDT': 64000 } });
    });

    expect(result.current.prices.BTC.flashClass).toBe('');
    expect(result.current.prices.BTC.direction).toBe('none');
  });

  it('reports no 24h change rather than a flat one', () => {
    // The snapshot carries a price and nothing else. Zero would read as "this
    // asset is unchanged on the day", which is a different claim.
    const { result, socket } = connected();

    act(() => {
      socket.deliver({ type: 'snapshot', prices: { 'BTC/USDT': 64000 } });
    });

    expect(result.current.prices.BTC.change_24h).toBeNull();
  });

  it('lets a live update that arrived first win', () => {
    // The server writes the snapshot before entering its loop, but nothing
    // makes the two atomic — and the update carries a direction and a change
    // the snapshot cannot.
    const { result, socket } = connected();

    act(() => {
      socket.deliver({
        type: 'price_update',
        symbol: 'BTCUSDT',
        price: 64500,
        change_24h: 2.1,
        direction: 'up',
      });
      socket.deliver({ type: 'snapshot', prices: { 'BTC/USDT': 64000 } });
    });

    expect(result.current.prices.BTC.price).toBe(64500);
    expect(result.current.prices.BTC.change_24h).toBe(2.1);
  });

  it('skips entries that are not finite numbers', () => {
    const { result, socket } = connected();

    act(() => {
      socket.deliver({
        type: 'snapshot',
        prices: { 'BTC/USDT': 64000, 'ETH/USDT': null, 'SOL/USDT': 'nope' },
      });
    });

    expect(Object.keys(result.current.prices)).toEqual(['BTC']);
  });

  it('survives a snapshot message with no prices', () => {
    const { result, socket } = connected();

    act(() => {
      socket.deliver({ type: 'snapshot' });
    });

    expect(result.current.prices).toEqual({});
  });
});

describe('normalizePriceSymbol', () => {
  it('folds both wire spellings onto one key', () => {
    expect(normalizePriceSymbol('BTC/USDT')).toBe('BTC');
    expect(normalizePriceSymbol('BTCUSDT')).toBe('BTC');
  });

  it('only strips the quote at the end', () => {
    // An unanchored replace would eat the first occurrence wherever it fell.
    expect(normalizePriceSymbol('USDTC/USDT')).toBe('USDTC');
  });

  it('leaves a pair quoted in something else alone', () => {
    expect(normalizePriceSymbol('BTC/USD')).toBe('BTCUSD');
  });
});
