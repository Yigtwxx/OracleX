'use client';

import { usePathname } from 'next/navigation';

import { bodyFont, displayFont } from '@/components/borsa/fonts';
import { resolveRealm } from '@/lib/nav-items';

/**
 * The marketing group's root element, and which palette it is painted in.
 *
 * The two products do not share a look. `/` is the dark terminal's own page;
 * `/borsa` is light, Turkish and set in different faces. Rather than build a
 * second header, footer and auth modal for it, this swaps the *tokens* — the
 * `.borsa` block in globals.css redefines `--bg`, `--surface`, `--fg` and the
 * rest, so every shared control below it comes up in the right palette without
 * knowing a second palette exists.
 *
 * A client component because the layout above it is static and the decision is
 * per-route. The class has to sit above `MarketingShell`, not inside the page,
 * or the header would stay dark over a light document.
 */
export default function MarketingTheme({ children }: { children: React.ReactNode }) {
  const isBist = resolveRealm(usePathname()) === 'bist';

  return (
    <div
      // See BistPageShell: CSS uppercase is language-sensitive and the Turkish
      // dotted `i` needs the tag to survive it.
      lang={isBist ? 'tr' : undefined}
      className={
        isBist
          ? `borsa ${displayFont.variable} ${bodyFont.variable} min-h-svh`
          : 'landing min-h-svh bg-bg text-fg'
      }
    >
      {children}
    </div>
  );
}
