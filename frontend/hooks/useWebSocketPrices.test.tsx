import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useWebSocketPrices } from './useWebSocketPrices';

/**
 * The lifecycle, not the price mapping.
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
