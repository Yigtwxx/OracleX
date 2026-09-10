import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ChartPanel from './ChartPanel';

/**
 * The header control, which used to be two buttons that did nothing.
 *
 * Both carried a `title` and a hover state and neither had an `onClick`, so
 * they were focusable, looked live, and answered a click with silence. The
 * settings one is gone — the TradingView widget renders its own toolbar, so a
 * second control there had no meaning that was not already taken — and the
 * fullscreen one now does what its icon promises.
 *
 * What is worth asserting is the *label*, not the API call. Fullscreen has
 * more than one author: Escape and the browser's own chrome leave it without
 * going through this button, so a component that tracked its own clicks would
 * offer "Exit fullscreen" over a panel that had already exited. Every test
 * below drives the state through the `fullscreenchange` event for that reason.
 */

vi.mock('@/store/useStore', () => ({
  useStore: () => ({ chartSymbol: 'BINANCE:BTCUSDT', selectedNews: null }),
}));

vi.mock('react-ts-tradingview-widgets', () => ({
  AdvancedRealTimeChart: () => <div data-testid="tv-widget" />,
}));

function setFullscreenSupport(enabled: boolean) {
  Object.defineProperty(document, 'fullscreenEnabled', {
    configurable: true,
    value: enabled,
  });
}

/** Pretend the browser put `element` (or nothing) into fullscreen. */
function enterFullscreen(element: Element | null) {
  Object.defineProperty(document, 'fullscreenElement', {
    configurable: true,
    value: element,
  });
  fireEvent(document, new Event('fullscreenchange'));
}

afterEach(() => {
  vi.restoreAllMocks();
  enterFullscreen(null);
});

describe('ChartPanel header', () => {
  it('no longer renders a settings button', () => {
    setFullscreenSupport(true);
    render(<ChartPanel />);

    expect(screen.queryByTitle('Settings')).toBeNull();
  });

  it('offers fullscreen once mounted', () => {
    setFullscreenSupport(true);
    render(<ChartPanel />);

    expect(screen.getByLabelText('Show the chart fullscreen')).toBeTruthy();
  });

  it('hides the control where the browser does not allow fullscreen', () => {
    // An iframe without `allowfullscreen` is the real case. A button that
    // cannot work is worse than no button — it is the state this file exists
    // to remove.
    setFullscreenSupport(false);
    render(<ChartPanel />);

    expect(screen.queryByLabelText('Show the chart fullscreen')).toBeNull();
  });

  it('asks the browser for fullscreen on the whole panel, not just the chart', () => {
    // The header has to come along: fullscreening the chart area alone would
    // drop the symbol and the exit control off the screen.
    setFullscreenSupport(true);
    const request = vi.fn();
    Element.prototype.requestFullscreen = request;

    const { container } = render(<ChartPanel />);
    fireEvent.click(screen.getByLabelText('Show the chart fullscreen'));

    expect(request).toHaveBeenCalledOnce();
    expect(request.mock.instances[0]).toBe(container.firstChild);
  });

  it('offers the way out once the browser reports it is fullscreen', () => {
    setFullscreenSupport(true);
    Element.prototype.requestFullscreen = vi.fn();

    const { container } = render(<ChartPanel />);
    enterFullscreen(container.firstChild as Element);

    expect(screen.getByLabelText('Exit fullscreen')).toBeTruthy();
  });

  it('exits when asked again', () => {
    setFullscreenSupport(true);
    Element.prototype.requestFullscreen = vi.fn();
    const exit = vi.fn();
    document.exitFullscreen = exit;

    const { container } = render(<ChartPanel />);
    enterFullscreen(container.firstChild as Element);
    fireEvent.click(screen.getByLabelText('Exit fullscreen'));

    expect(exit).toHaveBeenCalledOnce();
  });

  it('returns to the enter label when fullscreen is left elsewhere', () => {
    // Escape, or the browser's own exit affordance. Neither goes through the
    // button, and a component holding its own flag would still say "Exit".
    setFullscreenSupport(true);
    Element.prototype.requestFullscreen = vi.fn();

    const { container } = render(<ChartPanel />);
    enterFullscreen(container.firstChild as Element);
    enterFullscreen(null);

    expect(screen.getByLabelText('Show the chart fullscreen')).toBeTruthy();
  });

  it('stays quiet when the request is refused', () => {
    // A rejected promise here is ordinary — an untrusted gesture, or an iframe
    // policy. It must not surface as an unhandled rejection.
    setFullscreenSupport(true);
    Element.prototype.requestFullscreen = vi.fn().mockRejectedValue(new Error('denied'));

    render(<ChartPanel />);

    expect(() => fireEvent.click(screen.getByLabelText('Show the chart fullscreen'))).not.toThrow();
  });
});
