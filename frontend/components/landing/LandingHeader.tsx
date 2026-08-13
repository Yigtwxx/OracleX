'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Github } from 'lucide-react';
import type { AuthMode } from '@/components/auth/AuthCard';
import Logo from '@/components/ui/Logo';
import ShinyText from '@/components/ui/ShinyText';
import { useAuth } from '@/contexts/AuthContext';
import { REPO_URL } from '@/lib/landing/links';

interface LandingHeaderProps {
  onOpenAuth: (mode: AuthMode, trigger: HTMLElement) => void;
}

const GHOST_BUTTON =
  'rounded-md px-3 py-1.5 text-base text-fg-muted transition-colors hover:text-fg';

export default function LandingHeader({ onOpenAuth }: LandingHeaderProps) {
  const { user, loading } = useAuth();
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

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 flex h-14 items-center gap-2 px-4 transition-colors duration-200 sm:px-6 ${
        scrolled ? 'border-b border-line bg-bg/85 backdrop-blur' : 'border-b border-transparent'
      }`}
    >
      <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Oracle-X home">
        <Logo size={18} className="shrink-0 text-fg" />
        <span className="text-md font-semibold tracking-tight text-fg">Oracle-X</span>
      </Link>

      <div className="flex-1" />

      <div className="flex-1" />

      {/* Fixed width so resolving `loading` cannot shift the rest of the bar. */}
      <div className="flex min-w-[168px] items-center justify-end gap-1">
        {loading ? null : user ? (
          <Link
            href="/home"
            className="rounded-md border border-line px-3 py-1.5 text-base transition-colors hover:border-line-strong"
          >
            {/* React Bits' shine. The base colour is the page's own `--fg` so
                the label still reads as a header control between sweeps, and
                the highlight is white rather than tinted — a sheen crossing
                the glyphs, not a second accent competing with the CTA. */}
            <ShinyText
              text="Open terminal"
              disabled={reduceMotion}
              speed={4}
              delay={2}
              spread={110}
              color="var(--fg)"
              shineColor="#ffffff"
              className="text-base"
            />
          </Link>
        ) : (
          <>
            <button
              ref={signInRef}
              type="button"
              onClick={() => signInRef.current && onOpenAuth('signin', signInRef.current)}
              className={GHOST_BUTTON}
            >
              Sign in
            </button>
            <button
              ref={signUpRef}
              type="button"
              onClick={() => signUpRef.current && onOpenAuth('signup', signUpRef.current)}
              className="rounded-md border border-line px-3 py-1.5 text-base text-fg transition-colors hover:border-line-strong"
            >
              Sign up
            </button>
          </>
        )}
      </div>

      <a
        href={REPO_URL}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Oracle-X on GitHub"
        className="landing-riser ml-1 rounded-md p-1.5 text-fg-muted transition-colors"
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
