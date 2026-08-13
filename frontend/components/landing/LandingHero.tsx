'use client';

import GoTerminalButton from './GoTerminalButton';
import HeroAsk from './HeroAsk';
import HeroBoard from './HeroBoard';
import MetricStrip from './MetricStrip';
import { REPO_URL } from '@/lib/landing/links';

/**
 * `min-h-svh`, not `min-h-screen`: on mobile the dynamic viewport unit is what
 * keeps the CTA above the fold while the URL bar is still showing.
 */
export default function LandingHero() {
  return (
    // Top-aligned rather than centred, and it has to stay that way: the board
    // opens with a stretch of tape already running, and the lower two thirds of
    // this screen is where that tape lives. Centred copy would sit on top of
    // the one thing worth looking at.
    // `max()` rather than a bare vh: 9vh clears the 56px header comfortably on
    // a tall screen and collides with it on a short one, and the floor is what
    // keeps the eyebrow off the header on a laptop in landscape.
    <section className="relative flex min-h-svh flex-col justify-start px-6 pt-[max(6rem,9vh)] sm:px-10 lg:px-16">
      <div className="flex w-full flex-col gap-12 lg:flex-row lg:items-start lg:justify-between lg:gap-16">
        <div className="max-w-2xl">
          <p className="label mb-5 text-accent">Financial intelligence terminal</p>

          {/* The eyebrow above already says what this is, so the headline says
              what is different about it. Two short lines rather than one long
              one, because at display size a single line either wraps somewhere
              the writer did not choose or forces the type down a step. */}
          <h1 className="text-display-1 font-semibold text-fg">
            Analysis you can
            <br />
            check line by line.
          </h1>

          {/* The whole product in two paragraphs: what is on the board, then
              what reads it. Everything below this line is detail. */}
          <p className="mt-5 max-w-lg text-lead text-fg-muted">
            Crypto and US equities on one board — price and volume, on-chain flow and funding, the
            macro calendar, and the filings behind who is actually holding a name. One screen
            instead of five tabs and a guess about how they fit together.
          </p>

          <p className="mt-4 max-w-lg text-lead text-fg-muted">
            On top of it sits an analyst that gathers its evidence first and cites it, then gets
            argued with by a second pass before you ever read the conclusion. Ask it anything in
            plain language, and post what you find where other people can push back on it.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <GoTerminalButton size="lg" />
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border border-line px-5 py-2.5 text-md text-fg-muted transition-colors duration-200 hover:border-line-strong hover:text-fg"
            >
              View source
            </a>
          </div>

          <div className="mt-10">
            <MetricStrip />
          </div>
        </div>

        {/* The canvas keeps a 78px gutter for its price scale, so the board stops
            short of the right edge rather than sitting on the axis. */}
        <div className="flex w-full flex-col gap-4 lg:mr-16 lg:w-auto lg:pt-2">
          <HeroBoard />
          <HeroAsk />
        </div>
      </div>
    </section>
  );
}
