'use client';

import { useState } from 'react';
import { logoCandidates, type MarketType } from '@/lib/asset-logo';

interface AssetLogoProps {
  symbol: string;
  /** The mark the API supplied, when it supplied one. */
  providedLogo?: string | null;
  marketType: MarketType;
  className?: string;
  /** Pixel size requested from the initials fallback; keep it ≥ the CSS size. */
  size?: number;
  /**
   * Decorative by default. The symbol is spelled out beside every one of these,
   * and an alt text here would have a screen reader read the ticker twice.
   */
  alt?: string;
}

/**
 * An asset's mark, with the fallback chain walked in the browser.
 *
 * Failures are tracked by URL rather than by index so a changed `symbol` needs
 * no reset: the new asset's URLs were never in the failed set, so it starts at
 * the top of its own chain. An index would have carried the old asset's
 * position over and skipped straight to initials for the next one.
 */
export default function AssetLogo({
  symbol,
  providedLogo,
  marketType,
  className = '',
  size = 64,
  alt = '',
}: AssetLogoProps) {
  const [failed, setFailed] = useState<string[]>([]);
  const chain = logoCandidates(symbol, providedLogo, marketType, size);
  const index = chain.findIndex((url) => !failed.includes(url));
  // Everything failed, including the initials host. Keep the last URL rather
  // than rendering a broken-image glyph, and stop advancing.
  const current = index === -1 ? chain[chain.length - 1] : chain[index];
  const hasNext = index !== -1 && index < chain.length - 1;

  return (
    <img
      src={current}
      alt={alt}
      className={className}
      loading="lazy"
      onError={() => {
        if (!hasNext) return;
        setFailed((previous) => (previous.includes(current) ? previous : [...previous, current]));
      }}
    />
  );
}
