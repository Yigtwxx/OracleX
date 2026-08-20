import type { TimeframeRead } from '@/store/useStore';
import {
  formatSignedPercent,
  rsiTone,
  slopeMark,
  trendTone,
  UNKNOWN,
  type Tone,
} from '@/lib/technical-format';

const TONE_TEXT: Record<Tone, string> = {
  up: 'text-up',
  down: 'text-down',
  warn: 'text-warn',
  muted: 'text-fg-muted',
};

const TONE_PILL: Record<Tone, string> = {
  up: 'bg-up-bg text-up',
  down: 'bg-down-bg text-down',
  warn: 'bg-warn-bg text-warn',
  muted: 'bg-surface-2 text-fg-muted',
};

/* Written out rather than derived from TONE_TEXT: Tailwind scans source text,
   so a class assembled at runtime is a class it never generates — the marker
   would render transparent with no error anywhere. */
const TONE_MARKER: Record<Tone, string> = {
  up: 'bg-up',
  down: 'bg-down',
  warn: 'bg-warn',
  muted: 'bg-fg-muted',
};

/**
 * The same chart read on three timeframes, one row each.
 *
 * A table rather than a stack of divs because that is what it is: three
 * measurements of four things, and a reader compares down the columns. It also
 * means a screen reader announces "1w, trend, bearish" instead of six
 * unattributed numbers in a row.
 */
export default function TimeframeGrid({ reads }: { reads: TimeframeRead[] }) {
  if (!reads.length) return null;

  return (
    <table className="w-full border-collapse">
      <caption className="sr-only">Trend, RSI and volatility on each timeframe</caption>
      <thead>
        <tr className="border-b border-line">
          <th scope="col" className="label pb-1 text-left">
            TF
          </th>
          <th scope="col" className="label pb-1 text-left">
            Trend
          </th>
          <th scope="col" className="label pb-1 text-left">
            RSI 14
          </th>
          <th scope="col" className="label pb-1 text-right">
            ATR
          </th>
        </tr>
      </thead>
      <tbody>
        {reads.map((read) => {
          const rsi = read.rsi;
          const value = typeof rsi?.value === 'number' ? rsi.value : null;
          const tone = rsiTone(rsi);

          return (
            <tr key={read.timeframe} className="border-b border-line last:border-0">
              <th scope="row" className="py-1.5 text-left align-top">
                <span className="font-mono text-sm uppercase text-fg">{read.timeframe}</span>
                {read.covers_days ? (
                  <span className="block text-2xs text-fg-subtle tabnum">{read.covers_days}d</span>
                ) : null}
              </th>

              <td className="py-1.5 align-top">
                <span
                  className={`inline-block rounded px-1.5 py-0.5 text-2xs ${TONE_PILL[trendTone(read.trend)]}`}
                >
                  {read.trend ?? UNKNOWN}
                </span>
              </td>

              <td className="py-1.5 align-top">
                <span className={`font-mono text-sm tabnum ${TONE_TEXT[tone]}`}>
                  {value === null ? UNKNOWN : value.toFixed(1)}
                </span>
                {typeof rsi?.change_5_bars === 'number' && (
                  <span className="ml-1 text-2xs text-fg-subtle tabnum">
                    {slopeMark(rsi.slope)} {rsi.change_5_bars > 0 ? '+' : ''}
                    {rsi.change_5_bars.toFixed(1)}
                  </span>
                )}
                {/* Named as well as coloured. Overbought and oversold share the
                    warning tone, so the tint alone cannot say which one this is —
                    and a reader who does not see colour would get nothing. */}
                {rsi?.signal && <span className="block text-2xs text-fg-subtle">{rsi.signal}</span>}
                {value !== null && (
                  /* 30 and 70 are drawn as ticks rather than described, because
                     the value beside the bar already carries the reading — the
                     bar only says how far from the extremes it is. */
                  <span
                    className="relative mt-1 hidden h-1 w-16 rounded-full bg-surface-2 sm:block"
                    aria-hidden="true"
                  >
                    <span className="absolute inset-y-0 left-[30%] w-px bg-line" />
                    <span className="absolute inset-y-0 left-[70%] w-px bg-line" />
                    <span
                      className={`absolute top-1/2 -mt-[3px] -ml-[3px] h-1.5 w-1.5 rounded-full ${TONE_MARKER[tone]}`}
                      style={{ left: `${value}%` }}
                    />
                  </span>
                )}
              </td>

              <td className="py-1.5 text-right align-top font-mono text-sm tabnum text-fg-muted">
                {formatSignedPercent(read.atr_percent, 2).replace('+', '')}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
