/**
 * Colour assignment for the ownership allocation bar.
 *
 * Lives under `lib/` with the other pure-function tests even though the module
 * sits in `components/`: it is plain data in, plain data out, and the rule it
 * pins is the one the bar exists for — that no two segments of one bar can be
 * mistaken for each other.
 */

import { describe, expect, it } from 'vitest';
import { allocationColors, allocationColorsByKey } from '@/components/ownership/format';

type Slice = Parameters<typeof allocationColors>[0][number];

const slice = (key: string, symbol: string | null, asset_class = 'equity'): Slice =>
  ({ key, symbol, asset_class }) as Slice;

describe('allocationColors', () => {
  it('gives a company its own colour', () => {
    const [coke, amex] = allocationColors([slice('ko', 'KO'), slice('axp', 'AXP')]);

    expect(coke.hex).toBe('#F5333F');
    expect(amex.hex).toBe('#7FB3E8');
  });

  it('refuses a brand colour a neighbouring segment already claimed', () => {
    // Coca-Cola red and Netflix red are the same red. The second one has to
    // fall through to the rotation or the two segments read as one holding.
    const [coke, netflix] = allocationColors([slice('ko', 'KO'), slice('nflx', 'NFLX')]);

    expect(coke.hex).toBe('#F5333F');
    expect(netflix.hex).toBeUndefined();
    expect(netflix.fill).toBeTruthy();
  });

  it('keeps bitcoin and ether on their own tokens rather than the rotation', () => {
    const [btc, eth] = allocationColors([
      slice('btc', 'BTC', 'crypto'),
      slice('eth', 'ETH', 'crypto'),
    ]);

    expect(btc.fill).toBe('bg-data-btc');
    expect(eth.fill).toBe('bg-data-eth');
  });

  it('leaves cash grey and never spends a hue on it', () => {
    const [cash] = allocationColors([slice('cash', null, 'cash')]);

    expect(cash.fill).toBe('bg-chart-6');
    expect(cash.hex).toBeUndefined();
  });

  it('never repeats a fill inside one bar', () => {
    const colors = allocationColors([
      slice('a', null),
      slice('b', null),
      slice('c', null),
      slice('d', null),
      slice('e', null),
    ]);

    const fills = colors.map((c) => c.hex ?? c.fill);
    expect(new Set(fills).size).toBe(fills.length);
  });

  it('maps a holding key to the colour its segment wears', () => {
    const byKey = allocationColorsByKey([slice('ko', 'KO'), slice('nvda', 'NVDA')]);

    expect(byKey.ko.hex).toBe('#F5333F');
    expect(byKey.nvda.hex).toBe('#76B900');
  });
});
