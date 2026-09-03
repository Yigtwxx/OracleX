import Reveal from './Reveal';
import TapeRule from './TapeRule';

interface DocMastheadProps {
  eyebrow: string;
  title: string;
  dek: string;
  /** A mono line of figures under the tape. Omitted where there are none. */
  stat?: string;
}

/**
 * The top of a documentation page: a claim, a sentence, and a strip of tape.
 *
 * The tape is what keeps this from being a heading on an empty screen. It is
 * also the page's only unprompted motion — everything below moves because you
 * scrolled to it, and something has to move because you arrived.
 */
export default function DocMasthead({ eyebrow, title, dek, stat }: DocMastheadProps) {
  return (
    <header className="pt-[max(6rem,9vh)]">
      <Reveal>
        <div className="mb-5 flex items-center gap-2.5">
          <span className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
            {eyebrow}
          </span>
          <span className="flex-1 border-t border-dashed border-line" />
        </div>

        <h1 className="text-display-1 font-semibold tracking-tight text-fg">{title}</h1>
        <p className="mt-5 max-w-xl text-lead text-fg-muted">{dek}</p>
      </Reveal>

      <div className="mt-10">
        <TapeRule />
      </div>

      {stat && (
        <p className="mt-3 font-mono text-2xs tabnum text-fg-subtle">{stat}</p>
      )}
    </header>
  );
}
