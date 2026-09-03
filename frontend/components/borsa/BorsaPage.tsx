'use client';

import { QueryClientProvider } from '@tanstack/react-query';
import Link from 'next/link';

import GoTerminalButton from '@/components/landing/GoTerminalButton';
import { REPO_URL } from '@/lib/landing/links';
import { BIST_NAV_ITEMS } from '@/lib/nav-items';
import { queryClient } from '@/lib/queryClient';
import {
  CoverageLine,
  LiveDeflation,
  LiveFundRisk,
  LiveKapTape,
  LiveMarket,
  LivePositioning,
} from './LiveBlocks';
import RealReturnHero from './RealReturnHero';
import SessionRail from './SessionRail';

/**
 * ─ DIRECTION ────────────────────────────────────────────────────────────────
 * THESIS: this page is a trading board. In Turkey a return is read twice, and
 * every figure here turns over into its second reading. It refuses the two
 * arrangements this category ships — the dark terminal with a wall of green
 * candles, which `/` already is, and its predictable opposite, a white SaaS page
 * with a strip of product screenshots.
 *
 * OWN-WORLD: cool paper (#eaeef2), one structural device (the `.borsa-row`
 * hairline), Bricolage Grotesque 800 display over a Source Serif body, mono
 * instrument labels. One ink-dark object on the paper — the board — with its
 * own palette, because green and red that clear contrast on paper do not clear
 * it on ink. Green and red mean measurement, never interface.
 *
 * STORY: a nominal gain is physically turned over into what it was worth →
 * the same thing is shown to be true of the whole fund board, not one fund →
 * live BIST, positioning and KAP evidence → the terminal's seven doors, named.
 *
 * FIRST VIEWPORT: eyebrow, two-line Bricolage headline and serif lede on the
 * left; the board on the right, its figure flipping from +%31,5 to %-0,2 with
 * the division printed under it. The primary action sits in the header.
 *
 * FORM: trading board plus settlement-statement grammar. First on the derived
 * list (others considered: the KAP filing form, the TÜİK bulletin table, the
 * newspaper agate market page, the bureau-de-change LED board).
 * ────────────────────────────────────────────────────────────────────────────
 *
 * Shares nothing with `/` but the header and the auth modal, and even those are
 * repainted by the `.borsa` token block. The other page is a dark, scroll-driven
 * scene in English; this one is a light Turkish document that holds still and
 * lets live figures carry the argument.
 *
 * It brings its own `QueryClientProvider`. The marketing group deliberately
 * renders outside `ClientShell` — no navigation, no readiness gate, and until
 * now no data — so the provider that the terminal takes for granted is simply
 * not above this tree. Scoping it here keeps that separation intact rather than
 * pulling the whole marketing group into the app's shell for one page.
 */

/**
 * The terminal, named.
 *
 * The page used to end on one button. A reader who has just accepted the
 * argument has no idea what they are being let into, and the header carries no
 * tabs on this route — so the doors are listed here, once, with what is behind
 * each one. Labels and paths come from the nav registry so a renamed tab cannot
 * drift out of sync with the page that advertises it.
 */
const DOOR_NOTES: Record<string, string> = {
  'bist-overview': 'Endeks, genişlik, sektörler',
  'bist-stocks': 'Tüm BIST hisseleri, reel getiri kolonuyla',
  'bist-funds': 'Bin TEFAS fonu, risk ölçümleriyle',
  'bist-smart-money': 'Halka açıklık, nispi hacim, VİOP',
  'bist-kap': 'Bildirim akışı ve tedbir duyuruları',
  'bist-viop': 'Vadeli sözleşmeler, açık pozisyon',
  'bist-macro': 'TÜFE, politika faizi, kur',
};

export default function BorsaPage() {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionRail />

      <main className="borsa-main">
        <RealReturnHero />

        <div className="borsa-grid">
          <LiveDeflation />
          <CoverageLine />
          <LiveMarket />
          <LiveFundRisk />
          <LivePositioning />
          <LiveKapTape />

          {/* Kapanış. The session ends, and so does the page — the one place the
              rail's metaphor and the document's structure have to agree. */}
          <section className="borsa-close borsa-row">
            <div className="borsa-close-head">
              <div>
                <p className="borsa-label">Kapanış 18:00</p>
                <p className="borsa-display borsa-close-title mt-4">Sıradaki seansa hazır ol.</p>
              </div>
              <GoTerminalButton size="lg" className="shrink-0" />
            </div>

            <ul className="borsa-doors">
              {BIST_NAV_ITEMS.map((item) => (
                <li key={item.key}>
                  <Link href={item.href} className="borsa-door">
                    <span className="borsa-door-label">{item.label}</span>
                    <span className="borsa-door-note">{DOOR_NOTES[item.key]}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <footer className="borsa-footer borsa-row">
            <p className="borsa-footer-note">
              Burada yer alan bilgiler yatırım tavsiyesi değildir. Borsa İstanbul kaynaklı veriler
              en az 15 dakika gecikmelidir.
            </p>
            <span className="borsa-footer-meta">
              <span className="borsa-label borsa-footer-sources">
                Kaynaklar · Borsa İstanbul · TEFAS · KAP · TÜİK
              </span>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="borsa-label borsa-footer-link"
              >
                GitHub
              </a>
            </span>
          </footer>
        </div>
      </main>
    </QueryClientProvider>
  );
}
