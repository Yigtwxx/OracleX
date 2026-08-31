import MarketingShell from '@/components/landing/MarketingShell';
import MarketingTheme from '@/components/landing/MarketingTheme';

/**
 * The marketing group renders outside ClientShell on purpose: no navigation, no
 * global ticker, no BootGate readiness poll and — most importantly — no
 * `h-screen overflow-hidden`, so the landing page can actually scroll. It also
 * means `/` renders fine with the backend down, which is the one page that has
 * to.
 *
 * The header and the auth modal sit in `MarketingShell` here rather than in each
 * page so they survive a navigation between the tabs — see that file for why
 * that is load-bearing rather than tidiness.
 *
 * The root element itself is `MarketingTheme`, which decides the palette: this
 * group serves two products and they do not look alike.
 */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <MarketingTheme>
      <MarketingShell>{children}</MarketingShell>
    </MarketingTheme>
  );
}
