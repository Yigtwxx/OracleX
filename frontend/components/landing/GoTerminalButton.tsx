'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import ShinyText from '@/components/ui/ShinyText';

interface GoTerminalButtonProps {
  size?: 'md' | 'lg';
  className?: string;
}

/**
 * A Link rather than a button: it navigates, so middle-click, right-click and
 * copy-link all have to work. One component owns the label and the prefetch so
 * the two call sites cannot drift.
 *
 * The label carries React Bits' shine — the same component the header control
 * uses, so the page's two calls to action are visibly the same object. It runs
 * on its own rather than on hover: this is the primary action on a page whose
 * whole background is already moving, and a button that only does something
 * once you have found it is not helping you find it.
 *
 * What it replaced was a lift and a glow. Both were the button behaving like a
 * physical object — rising off the page, casting light onto it — on a surface
 * that is otherwise a flat terminal readout, and the glow in particular put a
 * white halo on top of a chart it was meant to sit in front of.
 */
export default function GoTerminalButton({ size = 'md', className = '' }: GoTerminalButtonProps) {
  const scale = size === 'lg' ? 'px-5 py-2.5 text-lead' : 'px-4 py-2 text-base';
  const [reduceMotion, setReduceMotion] = useState(false);

  // The sweep runs on a rAF loop inside a motion value, so the global
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
    <Link
      href="/home"
      prefetch
      className={`group inline-flex items-center gap-2 rounded-md bg-accent font-medium ${scale} ${className}`}
    >
      {/* Dark glyphs on a white fill, so the shine is the label *lightening*
          rather than a white sheen — there is nothing brighter than the button
          for a highlight to be made of. Mixed towards the fill rather than set
          to a flat grey so it tracks the accent, and stopped at 60% because the
          band crossing a glyph still has to clear the contrast floor while it
          is over it. */}
      <ShinyText
        text="Go Terminal"
        disabled={reduceMotion}
        speed={3}
        delay={2.4}
        spread={110}
        color="var(--accent-fg)"
        shineColor="color-mix(in srgb, var(--accent-fg) 60%, var(--accent))"
      />
      <ArrowRight
        className="h-4 w-4 text-accent-fg transition-transform duration-200 group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </Link>
  );
}
