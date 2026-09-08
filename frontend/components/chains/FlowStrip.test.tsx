import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ChainsBoardResponse } from '@/lib/api';
import FlowStrip from './FlowStrip';

/**
 * The guard here is `assets.some(asset => net_flow_usd !== null || …)`, which
 * covers two cases that look nothing alike from outside: no assets at all, and
 * assets that arrived carrying no readings. Both must say the feed is
 * unavailable rather than drawing a strip of dashes that reads as zero flow.
 *
 * Direction is the other claim worth pinning. Onto an exchange is what precedes
 * selling, so an inflow is the bearish colour — the opposite of the reading a
 * positive number invites.
 */

type Flows = ChainsBoardResponse['flows'];

function flows(overrides: Partial<Flows> = {}): Flows {
  return {
    as_of: '2026-09-07',
    assets: [
      {
        symbol: 'BTC',
        net_flow_usd: -42_000_000,
        active_addresses: 812_000,
        transactions: 410_000,
      },
    ],
    ...overrides,
  };
}

describe('FlowStrip', () => {
  it('reports unavailable when no asset is covered', () => {
    render(<FlowStrip flows={flows({ assets: [] })} />);

    expect(screen.getByText('Flow data is unavailable.')).toBeInTheDocument();
  });

  it('reports unavailable when the assets arrived with no readings in them', () => {
    render(
      <FlowStrip
        flows={flows({
          assets: [
            { symbol: 'BTC', net_flow_usd: null, active_addresses: null, transactions: 4 },
            { symbol: 'ETH', net_flow_usd: null, active_addresses: null, transactions: null },
          ],
        })}
      />
    );

    // `transactions` is deliberately not part of the guard: a transaction count
    // with no flow behind it is not what this strip is for.
    expect(screen.getByText('Flow data is unavailable.')).toBeInTheDocument();
  });

  it('renders a row per asset once any reading exists', () => {
    render(
      <FlowStrip
        flows={flows({
          assets: [
            {
              symbol: 'BTC',
              net_flow_usd: -42_000_000,
              active_addresses: 812_000,
              transactions: 1,
            },
            { symbol: 'ETH', net_flow_usd: 18_000_000, active_addresses: 500_000, transactions: 2 },
          ],
        })}
      />
    );

    expect(screen.getByText('BTC')).toBeInTheDocument();
    expect(screen.getByText('ETH')).toBeInTheDocument();
    expect(screen.queryByText('Flow data is unavailable.')).toBeNull();
  });

  it('colours an inflow as the bearish direction and names it', () => {
    render(
      <FlowStrip
        flows={flows({
          assets: [
            { symbol: 'ETH', net_flow_usd: 18_000_000, active_addresses: 500_000, transactions: 2 },
          ],
        })}
      />
    );

    expect(screen.getByText('onto exchanges')).toBeInTheDocument();
    expect(screen.getByText('+$18.0M').className).toContain('text-down');
  });

  it('colours an outflow as the bullish direction and names it', () => {
    render(<FlowStrip flows={flows()} />);

    expect(screen.getByText('off exchanges')).toBeInTheDocument();
    expect(screen.getByText('−$42.0M').className).toContain('text-up');
  });

  it('prints an absent flow as no reading rather than as zero', () => {
    render(
      <FlowStrip
        flows={flows({
          assets: [
            { symbol: 'BTC', net_flow_usd: null, active_addresses: 812_000, transactions: null },
          ],
        })}
      />
    );

    // "$0" would assert a balanced day, which is a measurement nobody made.
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByText('$0')).toBeNull();
  });

  it('shows no reading in the header when the feed carries no date', () => {
    render(<FlowStrip flows={flows({ as_of: null })} />);

    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
