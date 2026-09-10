import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { MarketOverview } from '@/lib/api';

/**
 * What the overview does when the board cannot be fetched.
 *
 * It used to do nothing. `OverviewPage` never read `isError` from any of its
 * queries, so a 500 on `/api/market-overview` left `isLoading` false and
 * `marketData` null — and every panel below drew its own version of empty: a
 * table with a header and no rows, a breadth strip reading zero, a
 * distribution with no bars. Six blank panels are not a neutral state on a
 * markets page; they say the market is empty, which is a claim about the world
 * rather than a gap in the data.
 *
 * The distinction the tests below turn on is `isError && !marketData`. React
 * Query hands back the last good payload while a refetch is failing, and a
 * stale board is worth more to a reader than an apology — so the message is
 * only for the case where there is genuinely nothing to draw.
 */

const useMarketOverview = vi.fn();
const useNasdaqOverview = vi.fn();
const useFearGreedIndex = vi.fn();

vi.mock('@/hooks/queries', () => ({
  useMarketOverview: (...args: unknown[]) => useMarketOverview(...args),
  useNasdaqOverview: (...args: unknown[]) => useNasdaqOverview(...args),
  useFearGreedIndex: (...args: unknown[]) => useFearGreedIndex(...args),
}));

// The panels are stubbed: this is a test about which branch the page takes,
// and the real table opens a WebSocket.
vi.mock('./overview/MarketStatsBar', () => ({ default: () => <div /> }));
vi.mock('./overview/AssetListCard', () => ({ default: () => <div /> }));
vi.mock('./overview/AssetTable', () => ({
  default: () => <div data-testid="asset-table" />,
}));
vi.mock('./overview/MarketBreadthStrip', () => ({ default: () => <div /> }));
vi.mock('./overview/ChangeDistribution', () => ({ default: () => <div /> }));
vi.mock('./overview/DivergenceBoard', () => ({ default: () => <div /> }));
vi.mock('./FearGreedGauge', () => ({ default: () => <div /> }));

import OverviewPage from './OverviewPage';

function query(overrides: Record<string, unknown> = {}) {
  return {
    data: undefined,
    isLoading: false,
    isFetching: false,
    isError: false,
    dataUpdatedAt: 0,
    refetch: vi.fn(),
    ...overrides,
  };
}

const BOARD = {
  coins: [{ symbol: 'BTC', price: 1, change_24h: 1, volume_24h: 2_000_000 }],
} as unknown as MarketOverview;

beforeEach(() => {
  vi.clearAllMocks();
  useMarketOverview.mockReturnValue(query());
  useNasdaqOverview.mockReturnValue(query());
  useFearGreedIndex.mockReturnValue(query());
});

describe('OverviewPage when the board fails', () => {
  it('says so instead of drawing an empty market', () => {
    useMarketOverview.mockReturnValue(query({ isError: true }));

    render(<OverviewPage marketType="crypto" />);

    expect(screen.getByText(/board is unavailable/i)).toBeTruthy();
    expect(screen.queryByTestId('asset-table')).toBeNull();
  });

  it('offers a retry that refetches', () => {
    const refetch = vi.fn();
    useMarketOverview.mockReturnValue(query({ isError: true, refetch }));

    render(<OverviewPage marketType="crypto" />);
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    expect(refetch).toHaveBeenCalled();
  });

  it('names the market the reader is looking at', () => {
    useNasdaqOverview.mockReturnValue(query({ isError: true }));

    render(<OverviewPage marketType="nasdaq" />);

    expect(screen.getByText(/stock market board is unavailable/i)).toBeTruthy();
  });

  it('keeps a stale board rather than replacing it with an apology', () => {
    // A failing refetch on top of a good payload. The prices are old, but old
    // prices beat no prices, and the stats bar already carries the timestamp.
    useMarketOverview.mockReturnValue(query({ isError: true, data: BOARD }));

    render(<OverviewPage marketType="crypto" />);

    expect(screen.queryByText(/board is unavailable/i)).toBeNull();
    expect(screen.getByTestId('asset-table')).toBeTruthy();
  });

  it('does not blank the board when only Fear & Greed failed', () => {
    // One card's worth of missing data is not a reason to withhold two hundred
    // prices; the gauge handles having none of its own.
    useMarketOverview.mockReturnValue(query({ data: BOARD }));
    useFearGreedIndex.mockReturnValue(query({ isError: true }));

    render(<OverviewPage marketType="crypto" />);

    expect(screen.queryByText(/board is unavailable/i)).toBeNull();
    expect(screen.getByTestId('asset-table')).toBeTruthy();
  });

  it('draws the board normally when nothing failed', () => {
    useMarketOverview.mockReturnValue(query({ data: BOARD }));

    render(<OverviewPage marketType="crypto" />);

    expect(screen.queryByText(/board is unavailable/i)).toBeNull();
    expect(screen.getByTestId('asset-table')).toBeTruthy();
  });
});
