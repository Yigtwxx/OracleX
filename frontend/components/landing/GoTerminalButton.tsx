'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowRight } from 'lucide-react';

import { realmFor, resolveRealm } from '@/lib/nav-items';

interface GoTerminalButtonProps {
  size?: 'md' | 'lg';
  className?: string;
}

/**
 * A Link rather than a button: it navigates, so middle-click, right-click and
 * copy-link all have to work. One component owns the label and the prefetch so
 * the two call sites cannot drift.
 *
 * It is the header control at a larger size — outlined on the page's own black
 * rather than filled, same label, same hover. The page's two ways out are the
 * same object, and a reader who has already met one in the bar recognises the
 * other at the bottom instead of reading it as a different offer.
 *
 * At rest it does nothing. What was here before was React Bits' shine, running
 * on a loop; before that, a hover lift and an accent glow. The glow put a white
 * halo on a chart it was meant to sit in front of, and the shine was a second
 * moving thing on a page whose whole background already moves. The iridescence
 * on hover (`.landing-ultra`, in globals.css) is the whole of the button's
 * behaviour now, and it answers the pointer rather than competing for it.
 */
export default function GoTerminalButton({ size = 'md', className = '' }: GoTerminalButtonProps) {
  const scale = size === 'lg' ? 'px-5 py-2.5 text-lead' : 'px-4 py-2 text-base';
  // Reads the realm off the path rather than taking it as a prop: both call
  // sites are deep inside a page section, and threading it down would mean
  // every section in between had to know about realms to pass it along.
  const realm = realmFor(resolveRealm(usePathname()));

  return (
    <Link
      href={realm.href}
      prefetch
      // `bg-bg` rather than the header's transparent: the bar sits on flat page,
      // this sits on the tape still printing behind the outro veil, and a
      // see-through button there is a button with a chart moving inside it.
      className={`landing-ultra group inline-flex items-center gap-2 rounded-md border-[1.5px] border-line-strong bg-bg font-medium text-fg transition-colors hover:border-fg-subtle ${scale} ${className}`}
    >
      <span className="landing-ultra-slot">
        <span className="landing-ultra-base">{realm.copy.openTerminal}</span>
        {/* aria-hidden: the same word twice, and a screen reader should hear
            one control. */}
        <span aria-hidden="true" className="landing-ultra-ink">
          {realm.copy.openTerminal}
        </span>
      </span>
      <ArrowRight
        className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </Link>
  );
}
