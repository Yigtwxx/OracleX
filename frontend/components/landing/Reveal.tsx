'use client';

import { useEffect, useRef } from 'react';

interface RevealProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  /** Stagger within a group, in milliseconds. */
  delay?: number;
  className?: string;
}

/**
 * Fades content up the first time it enters the viewport, then stops watching.
 *
 * Driven by a CSS *transition* rather than an animation on purpose: the global
 * `prefers-reduced-motion` rule in globals.css collapses every animation to
 * 0.01ms, which would leave anything starting at `opacity: 0` permanently
 * invisible. A transition simply lands on its end state instantly.
 */
export default function Reveal({ children, delay = 0, className = '', ...rest }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const show = () => node.setAttribute('data-inview', '1');

    // Anything already scrolled past is shown outright. An IntersectionObserver
    // only reports threshold *crossings*, so content the page loaded above —
    // a restored scroll position, a deep link — goes from "below the viewport"
    // to "above" it without ever intersecting, and would sit at opacity 0 for
    // good. The observer cannot catch this case; the check has to happen here.
    if (node.getBoundingClientRect().bottom < 0) {
      show();
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting && entry.boundingClientRect.bottom >= 0) return;
        show();
        observer.disconnect();
      },
      { rootMargin: '-5% 0px -8% 0px' }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`landing-reveal ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
      {...rest}
    >
      {children}
    </div>
  );
}
