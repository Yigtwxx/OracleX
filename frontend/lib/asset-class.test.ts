import { describe, it, expect } from 'vitest';
import { assetClassOf } from './asset-class';

describe('assetClassOf', () => {
  it('reads the market off the exchange prefix', () => {
    expect(assetClassOf({ symbol: 'NASDAQ:NVDA' })).toBe('stock');
    expect(assetClassOf({ symbol: 'NYSE:JPM' })).toBe('stock');
    expect(assetClassOf({ symbol: 'BINANCE:BTCUSDT' })).toBe('crypto');
    expect(assetClassOf({ symbol: 'OKX:ETHUSDT' })).toBe('crypto');
  });

  it('does not care how the backend cased the prefix', () => {
    expect(assetClassOf({ symbol: 'nasdaq:AAPL' })).toBe('stock');
  });

  it('is unknown when no asset was attributed', () => {
    // The state that motivated the grey stripe: a rate decision or an index
    // recap, which the backend deliberately leaves unattributed rather than
    // pinning to a ticker it had to invent.
    expect(assetClassOf({ symbol: undefined })).toBe('unknown');
    expect(assetClassOf({ symbol: '' })).toBe('unknown');
  });

  it('is unknown for a prefix neither market claims, and for a bare ticker', () => {
    expect(assetClassOf({ symbol: 'FOREX:EURUSD' })).toBe('unknown');
    expect(assetClassOf({ symbol: 'BTCUSDT' })).toBe('unknown');
  });
});
