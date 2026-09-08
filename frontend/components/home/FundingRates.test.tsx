import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { FundingRate } from '@/lib/api';
import FundingRates from './FundingRates';

/**
 * Which branch the panel renders, plus the one derivation it makes from its
 * rows: 4h and 8h perpetuals are mixed in the same table, and the header counts
 * down to whichever settles first. That claim was written as a comment and
 * never checked, and it is the sort that quietly inverts under a refactor.
 */

const NOW = Date.UTC(2026, 8, 8, 12, 0, 0);

function rate(overrides: Partial<FundingRate> = {}): FundingRate {
  return {
    symbol: 'BTC-USDT-SWAP',
    rate: 0.0001,
    rate_formatted: '0.0100%',
    index_price: 64000,
    mark_price: 64010,
    next_funding_time: NOW + 3 * 3600_000,
    interval_hours: 8,
    is_extreme: false,
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('FundingRates', () => {
  it('shows the skeleton while loading', () => {
    const { container } = render(<FundingRates data={[rate()]} isLoading isError={false} />);

    expect(screen.queryByText('BTC-USDT-SWAP')).toBeNull();
    expect(container.querySelector('.shimmer')).not.toBeNull();
  });

  it('reports a failed feed rather than an empty one', () => {
    render(<FundingRates data={[]} isLoading={false} isError />);

    expect(screen.getByText('Funding rates unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No funding rates reported')).toBeNull();
  });

  it('says nothing was reported when the feed answered with an empty list', () => {
    render(<FundingRates data={[]} isLoading={false} isError={false} />);

    expect(screen.getByText('No funding rates reported')).toBeInTheDocument();
    expect(screen.queryByText('Funding rates unavailable')).toBeNull();
  });

  it.each([
    ['a failed feed', true],
    ['an empty one', false],
  ])('drops the column header and the countdown over %s', (_label, isError) => {
    render(<FundingRates data={[]} isLoading={false} isError={isError} />);

    // A header row over no rows describes a table that is not there.
    expect(screen.queryByText('Symbol')).toBeNull();
    expect(screen.queryByText('Est. APR')).toBeNull();
    expect(screen.queryByText(/Next funding/)).toBeNull();
  });

  it('counts down to the earliest settlement when intervals are mixed', () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);

    render(
      <FundingRates
        data={[
          rate({
            symbol: 'BTC-USDT-SWAP',
            interval_hours: 8,
            next_funding_time: NOW + 3600_000 * 5,
          }),
          rate({
            symbol: 'ETH-USDT-SWAP',
            interval_hours: 4,
            next_funding_time: NOW + 3600_000 * 2,
          }),
        ]}
        isLoading={false}
        isError={false}
      />
    );

    // The nearer of the two, not the first in the array and not the last.
    expect(screen.getByText('2h 00m 00s')).toBeInTheDocument();
  });

  it('badges only the row that cleared the extreme threshold', () => {
    render(
      <FundingRates
        data={[
          rate({ symbol: 'BTC-USDT-SWAP', is_extreme: false }),
          rate({ symbol: 'ETH-USDT-SWAP', is_extreme: true }),
        ]}
        isLoading={false}
        isError={false}
      />
    );

    expect(screen.getAllByText('EXTREME')).toHaveLength(1);
  });

  it('extrapolates the APR from the rate and its own settlement period', () => {
    render(
      <FundingRates
        data={[rate({ rate: 0.0001, interval_hours: 8 })]}
        isLoading={false}
        isError={false}
      />
    );

    // 0.01% every eight hours, held for a year — not a quoted APR, which is why
    // the panel says "Est." beside it.
    expect(screen.getByText('10.95%')).toBeInTheDocument();
  });
});
