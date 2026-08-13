/**
 * One exchange with the oracle, under the board manifest.
 *
 * The headline promises "Ask the oracle" and, until this panel existed, the
 * first screen contained no evidence that anything could be asked anything. The
 * manifest above says what the terminal has; this says what it does with it.
 *
 * The answer is the point and the chips under it are the argument: a paragraph
 * about order-flow is worth nothing unless the rows behind it are named, and
 * naming them is the whole product. Everything here is fixed copy — a hero that
 * mocked up live data would be claiming something the page cannot back.
 */

/** What the answer was built from. Kept short — these are labels, not prose. */
const SOURCES: readonly string[] = ['ohlcv 4h', 'funding', 'depth'];

export default function HeroAsk() {
  return (
    // A plate rather than a note: the bracketed panel above is the primary
    // object in this column, and two sets of corner brackets stacked on each
    // other would leave neither of them meaning anything.
    // Hidden below `lg` because the gap it fills only exists at that width —
    // on a phone the hero is already a full column of stacked panels.
    <div className="landing-plate hidden w-full max-w-sm p-5 lg:block">
      <div className="mb-4 flex items-center gap-2.5">
        <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
          Oracle
        </span>
        <span className="flex-1 border-t border-dashed border-line" />
      </div>

      <p className="flex items-start gap-2 font-mono text-2xs text-fg">
        <span aria-hidden="true" className="text-accent">
          ›
        </span>
        why did BTC hold 56.9k?
      </p>

      <p className="mt-3 text-base text-fg-muted">
        Bid stacked 2.1× the 20-bar mean at that level, and funding flipped negative four hours
        before the wick.
      </p>

      <ul aria-label="Sources behind the answer" className="mt-4 flex flex-wrap gap-1.5">
        {SOURCES.map((source) => (
          <li
            key={source}
            className="border border-line px-1.5 py-0.5 font-mono text-2xs text-fg-subtle"
          >
            {source}
          </li>
        ))}
      </ul>
    </div>
  );
}
