'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Github } from 'lucide-react';
import type { AuthMode } from '@/components/auth/AuthCard';
import SessionBadge from '@/components/borsa/SessionBadge';
import RealmSwitcher from '@/components/RealmSwitcher';
import ShinyText from '@/components/ui/ShinyText';
import { useAuth } from '@/contexts/AuthContext';
import LandingTabs from './LandingTabs';
import { REPO_URL } from '@/lib/landing/links';
import { realmFor, resolveRealm } from '@/lib/nav-items';

interface LandingHeaderProps {
  onOpenAuth: (mode: AuthMode, trigger: HTMLElement) => void;
}

const GHOST_BUTTON =
  'rounded-md px-3 py-1.5 text-base text-fg-muted transition-colors hover:text-fg';

export default function LandingHeader({ onOpenAuth }: LandingHeaderProps) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const signInRef = useRef<HTMLButtonElement>(null);
  const signUpRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // The sweep is driven by a motion value on a rAF loop, so the global
  // `prefers-reduced-motion` rule in globals.css — which only reaches CSS
  // animations and transitions — cannot switch it off. This can.
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduceMotion(query.matches);
    sync();
    query.addEventListener('change', sync);
    return () => query.removeEventListener('change', sync);
  }, []);

  // Which product the reader is looking at. It decides both what the logo menu
  // offers and where "Open terminal" actually goes — sending someone reading
  // about Borsa İstanbul into the crypto board would be the wrong door.
  const realm = realmFor(resolveRealm(pathname));

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 flex h-14 items-center gap-2 px-4 transition-colors duration-200 sm:px-6 ${
        scrolled ? 'border-b border-line bg-bg/85 backdrop-blur' : 'border-b border-transparent'
      }`}
    >
      <RealmSwitcher activeRealm={realm.key} surface="marketing" className="" />

      {/* The section tabs are the global product's — Product, Developers, FAQ,
          all in English. The BIST page is a single Turkish page and reaches
          them through the logo menu, so it takes a session status line instead:
          the bar keeps its three-part layout, and the middle of it says
          something rather than holding a spacer open. */}
      {realm.key === 'global' ? <LandingTabs /> : <SessionBadge />}

      {/* Fixed width so resolving `loading` cannot shift the rest of the bar. */}
      <div className="flex min-w-[168px] items-center justify-end gap-1">
        {loading ? null : user ? (
          <Link
            href={realm.href}
            className="landing-ultra rounded-md border border-line px-3 py-1.5 text-base transition-colors hover:border-line-strong"
          >
            {/* React Bits' shine. The base colour is the page's own `--fg` so
                the label still reads as a header control between sweeps, and
                the highlight is white rather than tinted — a sheen crossing
                the glyphs, not a second accent competing with the CTA. */}
            <span className="landing-ultra-slot">
              {/* The sweep is a screen effect and its highlight is white. On the
                  BIST page's paper ground that is a white streak crossing dark
                  ink, which reads as a rendering fault rather than as a sheen —
                  and a printed board does not shimmer. */}
              <ShinyText
                text={realm.copy.openTerminal}
                disabled={reduceMotion || realm.key === 'bist'}
                speed={4}
                delay={2}
                spread={110}
                color="var(--fg)"
                shineColor="#ffffff"
                className="landing-ultra-base text-base"
              />
              {/* The hover state, as a second copy stacked over the first rather
                  than as a restyling of it: ShinyText paints its gradient through
                  inline styles that a CSS rule cannot outrank, so the only way to
                  hand the label a different gradient is to hand it a different
                  element. Same trick the GitHub mark below already uses.
                  aria-hidden because it is the same word twice — a screen reader
                  should hear one control, not two. */}
              <span aria-hidden="true" className="landing-ultra-ink">
                {realm.copy.openTerminal}
              </span>
            </span>
          </Link>
        ) : (
          <>
            <button
              ref={signInRef}
              type="button"
              onClick={() => signInRef.current && onOpenAuth('signin', signInRef.current)}
              className={GHOST_BUTTON}
            >
              {realm.copy.signIn}
            </button>
            <button
              ref={signUpRef}
              type="button"
              onClick={() => signUpRef.current && onOpenAuth('signup', signUpRef.current)}
              className="rounded-md border border-line px-3 py-1.5 text-base text-fg transition-colors hover:border-line-strong"
            >
              {realm.copy.signUp}
            </button>
          </>
        )}
      </div>

      <a
        href={REPO_URL}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Oracle-X on GitHub"
        // Hidden on a phone. The bar has to fit a logo, three tabs and two auth
        // controls inside 56px of height and whatever width is left, and this is
        // the one item already reachable from the footer on the same screen.
        className="landing-riser ml-1 hidden rounded-md p-1.5 text-fg-muted transition-colors sm:block"
      >
        <Github className="h-[18px] w-[18px]" aria-hidden="true" />
        <span aria-hidden="true" data-tone="mark" className="landing-riser-fill">
          <span className="landing-riser-ink">
            <Github className="h-[18px] w-[18px]" />
          </span>
        </span>
      </a>
    </header>
  );
}
