'use client';

import { useBistFunds } from '@/hooks/useBist';
import FlipFigure from './FlipFigure';

/**
 * The page's thesis, as a board that turns over.
 *
 * Live where it can be and a worked example where it cannot. The figures come
 * from the top of the TEFAS one-year table and the published annual inflation
 * rate, and the division that turns one into the other stays on screen — the
 * argument is that nominal returns mislead, and it would be self-defeating to
 * make it with a number nobody can verify.
 *
 * The fall-back is not an error state. This is the marketing group, `/` is
 * required to render with the backend down, and this page is the first here to
 * fetch anything — so when the data is not there the hero quietly becomes an
 * illustrative example and says so in the eyebrow. The claim does not change;
 * only whether it is being made about a real fund this week.
 *
 * The board is the one ink-dark object on a paper page, and it has its own
 * palette (`--borsa-board-*`) rather than the document's. That is not a theme
 * switch: green and red that clear 4.5:1 on paper do not clear it on ink, and a
 * figure this size is the last place on the page to guess.
 */

/** Used when the API cannot be reached. Real figures from the period, rounded. */
const EXAMPLE = { nominal: 1.48, inflation: 0.89, code: null as string | null };

const pct = (value: number) =>
  `%${(value * 100).toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}`;

const signed = (value: number) => `${value > 0 ? '+' : ''}${pct(value)}`;

export default function RealReturnHero() {
  // One fund is enough: the figures the hero needs are the board-wide summary,
  // which the API computes across all thousand rather than the page requested.
  const { data } = useBistFunds({ sort_by: '1y', limit: 1 });

  const inflation = data?.real_return?.inflation_yoy ?? null;
  const summary = data?.real_loss;
  const example = summary?.example ?? null;

  // The example is deliberately *not* the year's best fund.
  //
  // The first version used it, and the page argued against itself: the top
  // performer returned +1281% nominal and +948% real, so striking through the
  // first number to reveal the second said "you made a fortune either way".
  // The claim is that a lira gain can be a loss, and the case that shows it is
  // the largest gain that still ended negative — a fund up 31% that returned
  // nothing at all.
  const live =
    example && inflation !== null
      ? { nominal: example.nominal, inflation, code: example.code }
      : null;

  const { nominal, inflation: cpi, code } = live ?? EXAMPLE;
  const real = live ? example!.real : (1 + nominal) / (1 + cpi) - 1;

  return (
    <section className="borsa-hero px-6 pb-16 pt-24 sm:px-10 sm:pt-32 lg:px-20 lg:pt-36">
      <div className="borsa-grid">
        <div className="borsa-hero-copy">
          <p className="borsa-label">
            {live ? `TEFAS · ${code} · son 1 yıl` : 'Örnek hesap · TEFAS'}
          </p>

          <h1 className="borsa-display borsa-hero-title mt-6 text-balance">
            Nominal getiri, Türkiye&apos;de bir cümlenin yarısıdır.
          </h1>

          <p className="mt-7 max-w-xl text-lg leading-relaxed text-fg-muted sm:text-xl">
            {live ? 'Bu fon' : 'Bir fon'} son bir yılda {signed(nominal)} kazandırdı. Aynı dönemde
            TÜFE {pct(cpi)} olduğuna göre cebine giren {pct(real)}&apos;dir. Oracle-X her getiriyi
            ikinci yarısıyla birlikte gösterir.
          </p>

          {/* The proportion, not the anecdote. One fund that trailed inflation is
              a story; a third of them is the market. */}
          {summary && summary.count > 0 && (
            <p className="mt-5 max-w-xl text-base text-fg-muted">
              Geçen yıl ölçülebilen {summary.measured} fondan{' '}
              <strong className="font-semibold text-fg">{summary.count} tanesi</strong> nominalde
              kazandırdı, reelde kaybettirdi.
            </p>
          )}
        </div>

        {/* The board. One object, two readings, and the arithmetic underneath
            so a reader who does not believe the second can reproduce it. */}
        <figure className="borsa-board">
          <figcaption className="borsa-board-head">
            <span className="borsa-label borsa-board-label">
              {live ? `${code} · 1 yıl` : 'Örnek · 1 yıl'}
            </span>
            <span className="borsa-board-state">
              <span className="borsa-board-dot" aria-hidden="true" />
              {live ? 'TEFAS' : 'Örnek hesap'}
            </span>
          </figcaption>

          <div className="borsa-board-face">
            <FlipFigure
              className="borsa-board-slot"
              from="SANA GÖSTERİLEN"
              to="CEBİNE GİREN"
              label="Cebine giren"
            />

            <FlipFigure
              className="borsa-board-number borsa-figure"
              from={signed(nominal)}
              to={signed(real)}
              fromColor="var(--borsa-board-gain)"
              toColor={real >= 0 ? 'var(--borsa-board-gain)' : 'var(--borsa-board-loss)'}
              delayMs={340}
              label={`Reel getiri ${pct(real)}`}
            />
          </div>

          <div className="borsa-board-foot">
            <span className="borsa-board-struck">
              <span className="borsa-strike-slot">
                <span className="borsa-figure">{signed(nominal)}</span>
                <span className="borsa-strike" aria-hidden="true" />
              </span>
              <span className="borsa-board-struck-note">nominal</span>
            </span>

            {/* The division itself, on the board rather than under it: the proof
                and the claim should not be separated by a section rule. */}
            <span className="borsa-board-math borsa-figure">
              (1 + {nominal.toLocaleString('tr-TR', { maximumFractionDigits: 3 })}) ÷ (1 +{' '}
              {cpi.toLocaleString('tr-TR', { maximumFractionDigits: 3 })}) − 1 = {pct(real)}
            </span>
          </div>
        </figure>
      </div>
    </section>
  );
}
