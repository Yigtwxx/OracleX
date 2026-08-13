import Link from 'next/link';
import Logo from '@/components/ui/Logo';
import { REPO_URL } from '@/lib/landing/links';

const LINKS: readonly { readonly href: string; readonly label: string }[] = [
  { href: '/home', label: 'Terminal' },
  { href: '/analysis', label: 'Analysis' },
  { href: '/heatmap', label: 'Heatmap' },
  { href: '/community', label: 'Community' },
];

/**
 * Sits outside the canvas track, so the scene has already finished by the time
 * the footer is on screen and the render loop can stop.
 */
export default function LandingFooter() {
  return (
    // One band, pinned to the left edge rather than sitting in the page gutter:
    // the page ends on the tape, and a centred or inset footer would read as a
    // block of its own after it. The 12px inset is there so the mark does not
    // sit against the viewport edge itself.
    <footer className="relative z-10 border-t border-line bg-bg py-3 pl-3 pr-6">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-2">
        <div className="flex items-center gap-2">
          <Logo size={14} className="text-fg-muted" />
          <span className="text-sm font-semibold text-fg">Oracle-X</span>
        </div>

        <nav aria-label="Terminal sections" className="flex flex-wrap gap-x-5 gap-y-2">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-fg-muted transition-colors hover:text-fg"
            >
              {link.label}
            </Link>
          ))}
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-fg-muted transition-colors hover:text-fg"
          >
            Source
          </a>
        </nav>
      </div>
    </footer>
  );
}
