'use client';

import { useCallback, useRef, useState } from 'react';
import type { AuthMode } from '@/components/auth/AuthCard';
import { figureOf } from '@/lib/landing/imagery';
import { FEATURES, STAGES, type StageKey } from '@/lib/landing/stages';
import AuthModal from './AuthModal';
import FeatureSection from './FeatureSection';
import GoTerminalButton from './GoTerminalButton';
import LandingFooter from './LandingFooter';
import LandingGate from './LandingGate';
import LandingHeader from './LandingHeader';
import LandingHero from './LandingHero';
import Reveal from './Reveal';
import PassDiagram from './PassDiagram';
import ScrollCanvas from './ScrollCanvas';
import StageFigure from './StageFigure';
import TypedPoints from './TypedPoints';

function heightOf(key: StageKey): number {
  const stage = STAGES.find((s) => s.key === key);
  if (!stage) throw new Error(`Unknown stage: ${key}`);
  return stage.vh;
}

const printFigure = figureOf('print');

/**
 * The gap each of the seven panels below is an answer to.
 *
 * Questions rather than claims, and only three of them: the band's job is to
 * hand the reader something to hold while the tape prints, not to make the
 * argument a second time in shorter sentences.
 */
const OPEN_QUESTIONS: readonly string[] = [
  'Who is on the other side of this level, and how much of it do they hold?',
  'What repriced it — which print, which headline, at what hour?',
  'Has anyone else read it this way, and were they right the last time?',
];

export default function LandingPage() {
  const trackRef = useRef<HTMLDivElement>(null);
  const [authMode, setAuthMode] = useState<AuthMode | null>(null);
  const [authTrigger, setAuthTrigger] = useState<HTMLElement | null>(null);
  const [sceneReady, setSceneReady] = useState(false);

  const markSceneReady = useCallback(() => setSceneReady(true), []);

  const openAuth = useCallback((mode: AuthMode, trigger: HTMLElement) => {
    setAuthTrigger(trigger);
    setAuthMode(mode);
  }, []);

  const closeAuth = useCallback(() => setAuthMode(null), []);

  return (
    <>
      <LandingHeader onOpenAuth={openAuth} />
      <ScrollCanvas trackRef={trackRef} onReady={markSceneReady} />

      {/* The canvas track. Progress 0 → 1 is this element's scroll span, which is
          why the footer is deliberately outside it: the scene finishes, then the
          page does. */}
      <div ref={trackRef} className="relative z-10">
        <LandingHero />

        {/* The quiet band. Still sparse — this is where the tape prints, and copy
            here would be talking over the one thing worth watching — but two
            beats rather than one. At two screens tall a single centred panel
            leaves a full empty screen either side of itself, which reads as the
            page having stopped rather than as room to breathe. `justify-around`
            puts a beat in the middle of each screen instead, and adds no height:
            the section is still exactly what the stage schedule says it is. */}
        <section
          style={{ minHeight: `${heightOf('print')}svh` }}
          className="relative flex flex-col items-start justify-around px-6 sm:px-10 lg:px-16"
        >
          {/* Centred, which in a two-beat band means *between* the beats rather
              than beside either of them. It is the only slot in this section
              that keeps the page alternating: a picture level with the first
              panel would leave the two copy blocks adjacent in the scroll. */}
          {printFigure && <StageFigure figure={printFigure} align="center" />}

          <Reveal data-note-key="print" className="landing-note max-w-md p-5 sm:p-6">
            <p className="text-display-2 font-semibold leading-tight text-fg">
              A chart is an argument.
            </p>
            <p className="mt-3 text-md text-fg-muted">
              Every level someone draws is a claim about what other people will do at that price.
              Most tools show you the claim and stop there, which is why the same chart supports two
              opposite conclusions depending on who is reading it.
            </p>
            <p className="mt-3 text-md text-fg-muted">
              Oracle-X exists to make the claim checkable: the levels, the flow that defends them,
              the positioning underneath and the macro that reprices all three — on one screen,
              rather than in five tabs and a guess about how they fit together.
            </p>
          </Reveal>

          {/* The second beat. A plate rather than a note: only one panel per
              stage is wired to a bar, and giving this one the same brackets
              would promise a leader that never arrives. */}
          <Reveal delay={80} className="landing-plate max-w-md p-5 sm:p-6">
            <div className="mb-4 flex items-center gap-2.5">
              <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
                What the picture leaves out
              </span>
              <span className="flex-1 border-t border-dashed border-line" />
            </div>

            <TypedPoints
              items={OPEN_QUESTIONS}
              className="space-y-2.5"
              itemClassName="flex items-start gap-2.5 text-md text-fg"
            />

            <p className="mt-4 text-md text-fg-muted">
              Three things no chart says about itself. The rest of this page is the terminal
              answering them, one part at a time.
            </p>
          </Reveal>
        </section>

        {FEATURES.map((feature) => (
          <FeatureSection
            key={feature.key}
            feature={feature}
            vh={heightOf(feature.key)}
            // Only here. The stage claims the report is built in three passes
            // and then argued with; this is the one place on the page where
            // that can be shown rather than asserted.
            overlay={feature.key === 'ai' ? <PassDiagram /> : undefined}
          />
        ))}

        {/* The outro. Still the last stage of the schedule, so the canvas and the
            document stay the same length — but no longer empty: the page now
            closes on a line rather than on the tape running out.

            The veil is what makes that line the foreground. Everything above it
            competes for attention on purpose; here the tape is put out of focus
            so there is one thing left to read. It is masked rather than
            hard-edged because a blur that switches on at a section boundary
            reads as a rendering fault, not as a transition. */}
        <section
          aria-labelledby="outro-heading"
          style={{ minHeight: `${heightOf('tail')}svh` }}
          className="relative flex items-center justify-center px-6"
        >
          <div aria-hidden="true" className="landing-outro-veil absolute inset-0" />

          {/* One control, and nothing under it. A second link here would turn
              the last screen back into a choice, and the page has spent
              fourteen of them making the case for exactly one. */}
          <Reveal className="relative flex flex-col items-center text-center">
            <h2 id="outro-heading" className="text-display-1 font-semibold tracking-tight text-fg">
              Your financial brain
            </h2>
            <GoTerminalButton size="lg" className="mt-8" />
          </Reveal>
        </section>
      </div>

      <LandingFooter />

      <AuthModal mode={authMode} onClose={closeAuth} returnFocusTo={authTrigger} />

      {/* Last in the tree so it wins the stacking order without a z-index race. */}
      <LandingGate sceneReady={sceneReady} />
    </>
  );
}
