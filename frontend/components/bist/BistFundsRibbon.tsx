'use client';

import type { BistFundsResponse, BistSentiment } from '@/lib/bist-api';
import { formatPercent } from '@/lib/bist-format';
import { Divider, FearGreedStat, Stat, Track, moodColor } from './BistRibbon';

/**
 * The fund board's line of readings, in the same slot the equity ribbon uses.
 *
 * Deliberately not the equity ribbon with fund numbers substituted. Breadth,
 * limit-ups and turnover concentration are properties of a *session* on an
 * order book; a fund publishes one NAV a day and has none of them. What a fund
 * reader is actually asking on arrival is different: what does money cost
 * risk-free right now, and how much of the nominal return on the board below
 * survives inflation.
 *
 * Fear and greed is the exception and is shared verbatim with the equity
 * ribbon — it is the mood of the market these funds hold, so computing a
 * second version of it from NAVs would produce a different number for the same
 * question.
 */
export default function BistFundsRibbon({
  funds,
  sentiment,
}: {
  funds: BistFundsResponse;
  sentiment: BistSentiment | null;
}) {
  const loss = funds.real_loss;
  // Share of the *measured* funds, not of the whole board: a fund with no
  // deflator for the window was never tested, and counting it as a survivor
  // would flatter the figure.
  const lossShare = loss.measured > 0 ? (loss.count / loss.measured) * 100 : null;

  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-2xs">
      {sentiment ? (
        <FearGreedStat sentiment={sentiment} />
      ) : (
        <span className="text-fg-subtle">Duyarlılık endeksi için yeterli ölçüm yok</span>
      )}

      {funds.risk_free_rate != null && (
        <>
          <Divider />
          <Stat
            label="Risksiz faiz"
            title={
              funds.risk_free_source === 'money_market_median'
                ? 'Para piyasası fonlarının medyan yıllık getirisinden türetildi, TCMB politika faizinden değil'
                : 'Sharpe hesaplarının ölçüldüğü yıllık oran'
            }
          >
            <span className="tabnum font-mono text-fg">{formatPercent(funds.risk_free_rate)}</span>
          </Stat>
        </>
      )}

      {lossShare !== null && (
        <>
          <Divider />
          {/* The one reading on this line that a return table cannot show: a
              fund can top the board and still have lost the holder money. */}
          <Stat
            label="Enflasyona yenilen"
            title={`${loss.measured} fonun ${loss.count} tanesi ${loss.window} penceresinde nominal kazanıp reel kaybetti`}
          >
            <span
              className="tabnum font-mono font-semibold"
              // Inverted against the mood ramp: a high share here is the bad
              // end, where a high fear-and-greed score is not.
              style={{ color: moodColor(100 - lossShare) }}
            >
              {loss.count}/{loss.measured}
            </span>
            <Track percent={lossShare} color={moodColor(100 - lossShare)} />
          </Stat>
        </>
      )}

      <Divider />
      <Stat label={funds.fund_type_label} title="Bu tipte taranan fon sayısı">
        <span className="tabnum font-mono text-fg">{funds.total}</span>
      </Stat>
    </div>
  );
}
