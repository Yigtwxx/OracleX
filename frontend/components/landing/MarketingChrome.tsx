import LandingFooter from './LandingFooter';
import StaticBackdrop from './StaticBackdrop';

interface MarketingChromeProps {
  children: React.ReactNode;
}

/**
 * Backdrop and footer for the marketing pages that are not the tour.
 *
 * The header and the auth modal are not here — they live in the route group's
 * layout, so that the tab underline has something to slide across when you move
 * between pages. What is left is what genuinely differs from `/`: a still frame
 * of the board instead of a scroll-driven one.
 *
 * **`LandingGate` is deliberately absent, and copying it in here would be a
 * regression.** The gate holds the page shut until the canvas reports a painted
 * frame, because the landing page is genuinely dead until then — scrolling it
 * early scrolls a page that cannot answer. These pages are complete in the
 * server HTML. With nothing to report ready, the gate would release on its
 * two-and-a-half second ceiling, and the whole of that would be a black screen
 * and a locked scroll over a page that had finished rendering immediately.
 */
export default function MarketingChrome({ children }: MarketingChromeProps) {
  return (
    <>
      <StaticBackdrop />
      <div className="relative z-10">{children}</div>
      <LandingFooter />
    </>
  );
}
