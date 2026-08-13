/**
 * The marketing group renders outside ClientShell on purpose: no navigation, no
 * global ticker, no BootGate readiness poll and — most importantly — no
 * `h-screen overflow-hidden`, so the landing page can actually scroll. It also
 * means `/` renders fine with the backend down, which is the one page that has
 * to.
 */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return <div className="landing min-h-svh bg-bg text-fg">{children}</div>;
}
