import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ChainRow } from '@/lib/api';
import FeeRacer from './FeeRacer';

/**
 * The ordering and the amount control, which are the two things this panel
 * claims and neither of which was checked anywhere.
 *
 * The amount is the honest part of the design: a transfer costs the same
 * whether it moves ten dollars or ten million, so changing it must move the
 * percentage and leave the fee alone. A refactor that "helpfully" scaled the
 * fee by the amount would be a fabrication, and would pass every other test.
 */

function chain(key: string, overrides: Partial<ChainRow> = {}): ChainRow {
  return {
    key,
    name: key.toUpperCase(),
    symbol: 'ETH',
    family: 'evm',
    target_block_seconds: 12,
    explorer_block_url: `https://example.invalid/${key}/`,
    height: 1,
    last_block_at: null,
    block_time_seconds: null,
    cadence_span_seconds: null,
    tx_count: null,
    load: null,
    fee: { transfer_native: 0.001, transfer_usd: 1.5 },
    blocks: [],
    error: null,
    ...overrides,
  } as ChainRow;
}

describe('FeeRacer', () => {
  it('says so when every chain failed', () => {
    render(
      <FeeRacer
        chains={[
          chain('ethereum', { error: 'timeout', fee: null }),
          chain('base', { error: 'timeout', fee: null }),
        ]}
      />
    );

    expect(screen.getByText('No chain reported a fee')).toBeInTheDocument();
  });

  it('says so when chains reported but carried no fee', () => {
    // Distinct from the case above: these rows are healthy, the fee is simply
    // not in them, and an empty body would read as a rendering fault.
    render(<FeeRacer chains={[chain('ethereum', { fee: null }), chain('base', { fee: null })]} />);

    expect(screen.getByText('No chain reported a fee')).toBeInTheDocument();
  });

  it('orders the priced chains cheapest first', () => {
    const { container } = render(
      <FeeRacer
        chains={[
          chain('ethereum', { fee: { transfer_native: 0.001, transfer_usd: 3.2 } }),
          chain('base', { fee: { transfer_native: 0.000001, transfer_usd: 0.004 } }),
          chain('arbitrum', { fee: { transfer_native: 0.00001, transfer_usd: 0.02 } }),
        ]}
      />
    );

    const names = Array.from(container.querySelectorAll('.w-28')).map((el) => el.textContent);
    expect(names).toEqual(['BASE', 'ARBITRUM', 'ETHEREUM']);
  });

  it('sinks an unpriced chain to the bottom rather than sorting it as free', () => {
    // A null would land first in a plain numeric comparison, putting the one
    // chain whose cost is unknown at the top of a cheapest-first list.
    const { container } = render(
      <FeeRacer
        chains={[
          chain('solana', { fee: { transfer_native: 0.000005, transfer_usd: null } }),
          chain('ethereum', { fee: { transfer_native: 0.001, transfer_usd: 3.2 } }),
        ]}
      />
    );

    const names = Array.from(container.querySelectorAll('.w-28')).map((el) => el.textContent);
    expect(names).toEqual(['ETHEREUM', 'SOLANA']);
    // Both the fee and its share of the transfer go unread, rather than one of
    // them being computed from a price that is not there.
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('prints a genuinely zero fee as free rather than as a rounded zero', () => {
    render(<FeeRacer chains={[chain('tron', { fee: { transfer_native: 0, transfer_usd: 0 } })]} />);

    expect(screen.getByText('free')).toBeInTheDocument();
    expect(screen.queryByText('$0.00')).toBeNull();
  });

  it('changes the percentage and not the fee when the amount changes', () => {
    render(
      <FeeRacer
        chains={[chain('ethereum', { fee: { transfer_native: 0.001, transfer_usd: 3.2 } })]}
      />
    );

    expect(screen.getByText('$3.20')).toBeInTheDocument();
    expect(screen.getByText('0.320%')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '$100k' }));

    // The fee is unmoved — it prices computation and bytes, not value.
    expect(screen.getByText('$3.20')).toBeInTheDocument();
    expect(screen.getByText('0.003%')).toBeInTheDocument();
  });

  it('marks the active preset as pressed', () => {
    render(<FeeRacer chains={[chain('ethereum')]} />);

    expect(screen.getByRole('button', { name: '$1k' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '$100' })).toHaveAttribute('aria-pressed', 'false');
  });
});
