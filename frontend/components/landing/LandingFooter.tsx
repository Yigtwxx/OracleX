import Logo from '@/components/ui/Logo';

/**
 * Sits outside the canvas track, so the scene has already finished by the time
 * the footer is on screen and the render loop can stop.
 *
 * The mark and nothing else. It used to carry a row of links into the terminal,
 * which was a second navigation on a page whose whole argument is that there is
 * one thing to do next — and on the documentation pages it was a third, sitting
 * under a header that already names every section of the site.
 */
export default function LandingFooter() {
  return (
    // One band, pinned to the left edge rather than sitting in the page gutter:
    // the page ends on the tape, and a centred or inset footer would read as a
    // block of its own after it. The 12px inset is there so the mark does not
    // sit against the viewport edge itself.
    <footer className="relative z-10 border-t border-line bg-bg py-3 pl-3 pr-6">
      <div className="flex items-center gap-2">
        <Logo size={14} className="text-fg-muted" />
        <span className="text-sm font-semibold text-fg">Oracle-X</span>
      </div>
    </footer>
  );
}
