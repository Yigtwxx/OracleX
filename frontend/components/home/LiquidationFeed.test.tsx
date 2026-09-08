import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Liquidation } from '@/lib/api';
import LiquidationFeed from './LiquidationFeed';

/**
 * Which branch the panel renders, and nothing else.
 *
 * The bug this suite exists for: the parent passed no `isError`, so a failed
 * request arrived as `data ?? []` and the panel drew its "Live" badge over an
 * empty body. A reader could not tell a broken feed from a market in which
 * nobody had been liquidated — the two most different states the panel has.
 */

function liquidation(overrides: Partial<Liquidation> = {}): Liquidation {
  return {
    symbol: 'BTCUSDT',
    side: 'Long',
    price: 64000,
    amount_usd: 125000,
    time_ago: '2m ago',
    timestamp: 1_757_000_000_000,
    ...overrides,
  };
}

describe('LiquidationFeed', () => {
  it('shows the skeleton while loading, even holding data from the last poll', () => {
    const { container } = render(
      <LiquidationFeed data={[liquidation()]} isLoading isError={false} />
    );

    expect(screen.queryByText('BTCUSDT')).toBeNull();
    expect(container.querySelector('.shimmer')).not.toBeNull();
  });

  it('reports a failed feed rather than an empty one', () => {
    render(<LiquidationFeed data={[]} isLoading={false} isError />);

    expect(screen.getByText('Liquidations unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No liquidations in the window')).toBeNull();
  });

  it('says the window was quiet when the feed answered with nothing', () => {
    render(<LiquidationFeed data={[]} isLoading={false} isError={false} />);

    expect(screen.getByText('No liquidations in the window')).toBeInTheDocument();
    expect(screen.queryByText('Liquidations unavailable')).toBeNull();
  });

  it.each([
    ['a failed feed', true],
    ['an empty one', false],
  ])('does not claim to be Live over %s', (_label, isError) => {
    render(<LiquidationFeed data={[]} isLoading={false} isError={isError} />);

    // The badge is a claim about the feed. Over no rows it asserts a silent
    // market, which is the one reading these two states must not be given.
    expect(screen.queryByText('Live')).toBeNull();
  });

  it('renders a row per liquidation once there are any', () => {
    render(
      <LiquidationFeed
        data={[
          liquidation({ symbol: 'BTCUSDT' }),
          liquidation({ symbol: 'ETHUSDT', side: 'Short', timestamp: 1_757_000_001_000 }),
        ]}
        isLoading={false}
        isError={false}
      />
    );

    expect(screen.getByText('BTCUSDT')).toBeInTheDocument();
    expect(screen.getByText('ETHUSDT')).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('tints a liquidated long as the downward move', () => {
    render(
      <LiquidationFeed
        data={[
          liquidation({ symbol: 'BTCUSDT', side: 'Long' }),
          liquidation({ symbol: 'ETHUSDT', side: 'Short', timestamp: 1_757_000_001_000 }),
        ]}
        isLoading={false}
        isError={false}
      />
    );

    // A liquidated long is a forced sell, so the badge has to read as bearish
    // even though the word on it says "Long".
    expect(screen.getByText('Long').className).toContain('text-down');
    expect(screen.getByText('Short').className).toContain('text-up');
  });
});
