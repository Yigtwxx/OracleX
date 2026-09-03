import { describe, expect, it } from 'vitest';
import { mergeAssetOptions, matchScore, searchAssets, type AssetOption } from './asset-search';

const option = (partial: Partial<AssetOption> & { symbol: string }): AssetOption => ({
  name: partial.symbol,
  marketType: 'crypto',
  source: 'Crypto',
  ...partial,
});

describe('mergeAssetOptions', () => {
  it('keeps the first mention of a symbol', () => {
    const merged = mergeAssetOptions(
      [option({ symbol: 'BTC', source: 'My list' })],
      [option({ symbol: 'BTC', source: 'Crypto', rank: 1 })]
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].source).toBe('My list');
  });

  it('normalises what it stores', () => {
    expect(mergeAssetOptions([option({ symbol: ' $nvda ' })])[0].symbol).toBe('NVDA');
  });

  it('drops entries that normalise to nothing', () => {
    expect(mergeAssetOptions([option({ symbol: '  ' })])).toHaveLength(0);
  });
});

describe('matchScore', () => {
  it('ranks an exact ticker above every other kind of hit', () => {
    const exact = matchScore(option({ symbol: 'ADA', name: 'Cardano' }), 'ADA');
    const prefix = matchScore(option({ symbol: 'ADAUP', name: 'Ada Up' }), 'ADA');
    const inName = matchScore(option({ symbol: 'ABT', name: 'Adaptive Bio' }), 'ADA');
    expect(exact).toBeLessThan(prefix!);
    expect(prefix).toBeLessThan(inName!);
  });

  it('answers null for a row the query does not describe', () => {
    expect(matchScore(option({ symbol: 'BTC', name: 'Bitcoin' }), 'ADA')).toBeNull();
  });

  it('matches a name at word starts, not anywhere inside it', () => {
    // Both of these outranked half the board when names were tested as raw
    // substrings, because "ADA" sits inside them.
    expect(
      matchScore(option({ symbol: 'PC0000023', name: 'Tradable Singapore SSL' }), 'ADA')
    ).toBeNull();
    expect(matchScore(option({ symbol: 'META', name: 'MetaDAO' }), 'ADA')).toBeNull();
    // A second word still counts — nobody types the first word of a long name.
    expect(matchScore(option({ symbol: 'ABT', name: 'Adaptive Biotechnologies' }), 'BIO')).toBe(2);
  });

  it('treats an empty query as "everything qualifies"', () => {
    expect(matchScore(option({ symbol: 'BTC' }), '')).toBe(0);
  });
});

describe('searchAssets', () => {
  const universe = [
    option({ symbol: 'ADAUP', name: 'ADA Up', rank: 900 }),
    option({ symbol: 'ADA', name: 'Cardano', rank: 9 }),
    option({ symbol: 'BTC', name: 'Bitcoin', rank: 1 }),
    option({ symbol: 'ABT', name: 'Adaptive Biotechnologies', marketType: 'nasdaq', rank: 2000 }),
  ];

  it('puts the typed ticker first', () => {
    expect(searchAssets(universe, 'ada').map((row) => row.symbol)).toEqual(['ADA', 'ADAUP', 'ABT']);
  });

  it('orders an unfiltered list by market-cap rank', () => {
    expect(searchAssets(universe, '')[0].symbol).toBe('BTC');
  });

  it('sorts an unranked row last rather than first', () => {
    // A missing rank is unknown, not zero. Read as zero it once put obscure
    // watchlist entries above BTC.
    const withUnranked = [...universe, option({ symbol: 'ZZZ', name: 'Obscure' })];
    expect(searchAssets(withUnranked, '').at(-1)?.symbol).toBe('ZZZ');
  });

  it('treats a rank of zero as unranked, because the board reports it that way', () => {
    // The live case: "Tradable Singapore Fintech SSL" arrives with
    // `market_cap_rank: 0` and sat above Bitcoin until zero stopped counting.
    const withZero = [...universe, option({ symbol: 'PC0000023', name: 'Tradable SSL', rank: 0 })];
    expect(searchAssets(withZero, '')[0].symbol).toBe('BTC');
    expect(searchAssets(withZero, '').at(-1)?.symbol).toBe('PC0000023');
  });

  it('tolerates the decorations people paste', () => {
    expect(searchAssets(universe, ' $btc ').map((row) => row.symbol)).toEqual(['BTC']);
  });

  it('honours the limit', () => {
    expect(searchAssets(universe, '', 2)).toHaveLength(2);
  });
});
