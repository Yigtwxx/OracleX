import {
  formatSignedPercent,
  isRealLoss,
  realReturnNote,
  toneClass,
  EMPTY,
} from '@/lib/bist-format';
import type { FramedReturn } from '@/lib/bist-api';

interface ReturnCellProps {
  framed: FramedReturn | null | undefined;
  /** Show the dollar frame under the other two. Off in dense tables. */
  showUsd?: boolean;
  /**
   * Whether a real return is obtainable for this window *at all*.
   *
   * Different from `framed.real === null`, and the distinction is what keeps
   * the table readable. A null real return on one row among many means that row
   * is missing something. A null on every row of a column means the window
   * cannot be deflated at all — without an EVDS key that is every window except
   * the trailing year — and drawing six columns of em dashes down the whole
   * board is uniform noise rather than information. Those columns render the
   * nominal figure alone and the board carries one note explaining which
   * windows have a real column.
   */
  realAvailable?: boolean;
}

/**
 * One return, in the frames a Turkish reader needs it in.
 *
 * The signature of this whole realm. A lira return over a year in which
 * consumer prices rose about a third is half an answer, so the nominal figure
 * never appears here on its own.
 *
 * Three rules, each of which the naive version gets wrong:
 *
 * **A null real return is not zero.** It means the inflation series for that
 * window is unavailable — without an EVDS key that is every window except the
 * trailing year. It renders as an em dash with a tooltip that says so, never as
 * `%0,0`, which would state the opposite of what is known.
 *
 * **The nominal figure stays.** Hiding it would make this board look like it
 * disagreed with every other Turkish finance site rather than like it was
 * answering a question they do not ask.
 *
 * **A nominal gain that is a real loss is marked.** That is the single fact the
 * realm exists to surface and it is easy to miss when the two numbers sit in
 * the same colour.
 */
export default function ReturnCell({
  framed,
  showUsd = false,
  realAvailable = true,
}: ReturnCellProps) {
  if (!framed) {
    return <span className="text-fg-subtle">{EMPTY}</span>;
  }

  const realLoss = isRealLoss(framed);

  if (!realAvailable) {
    return (
      <span className={`tabnum ${toneClass(framed.nominal)}`}>
        {formatSignedPercent(framed.nominal)}
      </span>
    );
  }

  return (
    <span className="flex flex-col items-end leading-tight" title={realReturnNote(framed)}>
      <span className={`tabnum ${toneClass(framed.nominal)}`}>
        {formatSignedPercent(framed.nominal)}
      </span>
      <span
        className={`tabnum text-2xs ${
          framed.real === null ? 'text-fg-subtle' : toneClass(framed.real)
        }`}
      >
        {framed.real === null ? EMPTY : formatSignedPercent(framed.real)}
        {realLoss && (
          // The gap is the point: nominally up, actually down. A marker rather
          // than a colour change, because the colour already encodes direction.
          <span className="ml-1 text-down" aria-label="Nominal kazanç, reel kayıp">
            ▾
          </span>
        )}
      </span>
      {showUsd && (
        <span
          className={`tabnum text-2xs ${
            framed.usd === null ? 'text-fg-subtle' : toneClass(framed.usd)
          }`}
        >
          {framed.usd === null ? EMPTY : `${formatSignedPercent(framed.usd)} $`}
        </span>
      )}
    </span>
  );
}
