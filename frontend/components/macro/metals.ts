/**
 * Which commodity names wear their metal's own colour.
 *
 * The map moved to `lib/assetIdentity.ts` when the ownership board started
 * reporting the same metals under their spot symbols (XAU, GOLD) rather than
 * the futures contracts traded here (GC=F). Two maps would have drifted, and a
 * gold row rendering in one colour on Macro and another on Ownership is exactly
 * the failure the identity rule exists to prevent.
 *
 * This wrapper stays because the macro board speaks in contract symbols and
 * calls it by this name throughout.
 */

import { assetIdentityClass } from '@/lib/assetIdentity';

/** Classes for a commodity's name, or the ordinary foreground for everything else. */
export function metalClass(symbol: string, fallback = 'text-fg'): string {
  return assetIdentityClass(symbol, fallback);
}
