import {
  NO_READING,
  driftTone,
  formatMoney,
  formatPoints,
  formatProbability,
  outcomeColors,
} from '@/lib/polymarket-format';
import type { PolymarketMarketDetail } from '@/lib/api';

interface MarketDetailProps {
  detail: PolymarketMarketDetail;
}

const TONE_CLASS: Record<string, string> = {
  up: 'text-up',
  down: 'text-down',
  muted: 'text-fg-muted',
};

function Stat({ label, value, tone = 'muted' }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-2xs text-fg-subtle">{label}</div>
      <div className={`text-sm font-mono tabular-nums ${TONE_CLASS[tone] ?? 'text-fg'}`}>
        {value}
      </div>
    </div>
  );
}

/**
 * What the market itself says, before anything has been read about the world.
 *
 * Everything here is computed server-side without a model, which is the point:
 * when the bet analysis has too little evidence to reach a verdict, this panel
 * is still true and still worth looking at, so a refusal lands as a statement
 * about the evidence rather than as an empty screen.
 *
 * The gaps list is rendered rather than hidden. "No holder table was available"
 * and "this market has no concentrated holders" are opposite readings of the
 * same blank space, and the reader cannot tell them apart unless we say which.
 */
export default function MarketDetail({ detail }: MarketDetailProps) {
  const { facts, microstructure: micro } = detail;
  const colors = outcomeColors(facts.market.outcomes);
  const spikes = facts.moves.filter((m) => m.kind === 'spike');
  const opened = facts.moves.find((m) => m.kind === 'creation');

  return (
    <div className="p-4 space-y-4">
      {/* No question heading here: the dialog shell already carries it, and
          repeating it pushes the odds below the fold on a short window. */}
      {facts.market.end_date && (
        <p className="text-2xs text-fg-subtle">
          Resolves {new Date(facts.market.end_date).toISOString().slice(0, 10)}
        </p>
      )}

      <div className="flex flex-col gap-1">
        {facts.market.outcomes.map((outcome) => (
          <div key={outcome.label} className="flex items-baseline justify-between gap-3">
            <span
              className="text-xs truncate"
              style={{ color: colors[outcome.label] ?? 'var(--fg-muted)' }}
            >
              {outcome.label}
            </span>
            <span
              className="text-xs font-mono tabular-nums shrink-0"
              style={{ color: colors[outcome.label] ?? 'var(--fg-muted)' }}
            >
              {formatProbability(outcome.price)}
            </span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div>
          {/* "Leading" rather than "<outcome> price": on a market whose favoured
              side is called "No", the latter renders as "No price", which reads
              as a missing reading rather than as the price of No. */}
          <div className="text-2xs text-fg-subtle">
            Leading{micro.leading_outcome ? `: ${micro.leading_outcome}` : ''}
          </div>
          <div
            className="text-sm font-mono tabular-nums font-semibold"
            style={{
              color: micro.leading_outcome
                ? (colors[micro.leading_outcome] ?? 'var(--fg)')
                : 'var(--fg)',
            }}
          >
            {formatProbability(micro.leading_price)}
          </div>
        </div>
        <Stat
          label="24h move"
          value={formatPoints(micro.drift_24h)}
          tone={driftTone(micro.drift_24h)}
        />
        <Stat
          label="7d move"
          value={formatPoints(micro.drift_7d)}
          tone={driftTone(micro.drift_7d)}
        />
        <Stat label="Volume" value={formatMoney(micro.volume_usd)} />
        <Stat label="Liquidity" value={formatMoney(micro.liquidity_usd)} />
        <Stat label="Spread" value={micro.spread === null ? NO_READING : micro.spread.toFixed(3)} />
        <Stat label="Top holder" value={formatProbability(micro.top_holder_share)} />
        <Stat label="Top five" value={formatProbability(micro.top5_holder_share)} />
      </div>

      {micro.notes.length > 0 && (
        <ul className="space-y-1.5">
          {micro.notes.map((note) => (
            <li key={note} className="text-xs text-fg-muted leading-relaxed">
              {note}
            </li>
          ))}
        </ul>
      )}

      <div>
        <h3 className="text-xs font-semibold text-fg mb-2">When this market moved</h3>
        {spikes.length === 0 ? (
          <p className="text-xs text-fg-muted">
            No sharp repricing since it opened
            {opened ? ` on ${new Date(opened.started_at).toISOString().slice(0, 10)}` : ''}.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {spikes.map((move) => (
              <li key={move.started_at} className="flex items-baseline gap-2 text-xs">
                <span className="font-mono text-fg-muted tabular-nums shrink-0">
                  {new Date(move.started_at).toISOString().slice(0, 16).replace('T', ' ')}
                </span>
                <span className={`font-mono tabular-nums ${TONE_CLASS[driftTone(move.delta)]}`}>
                  {formatPoints(move.delta)}
                </span>
                <span className="text-fg-subtle">
                  {formatProbability(move.price_from)} → {formatProbability(move.price_to)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {facts.unavailable.length > 0 && (
        <div className="border-t border-line pt-3">
          <h3 className="text-2xs font-semibold text-fg-subtle mb-1">Not available</h3>
          <ul className="space-y-0.5">
            {facts.unavailable.map((gap) => (
              <li key={gap} className="text-2xs text-fg-subtle">
                {gap}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
