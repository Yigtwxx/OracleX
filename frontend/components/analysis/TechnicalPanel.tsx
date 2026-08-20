import { AlertTriangle } from 'lucide-react';
import type { TechnicalSignals } from '@/store/useStore';
import RangeStrip from './RangeStrip';
import TimeframeGrid from './TimeframeGrid';
import ZoneLadder from './ZoneLadder';

/** The pre-zone shape: two lists of preformatted bands and nothing else. */
function LegacyLevels({ technical }: { technical: TechnicalSignals }) {
  const groups = [
    { label: 'Support zones', levels: technical.support_levels, tone: 'bg-up-bg text-up' },
    {
      label: 'Resistance zones',
      levels: technical.resistance_levels,
      tone: 'bg-down-bg text-down',
    },
  ];

  return (
    <div className="space-y-2.5">
      {groups.map(({ label, levels, tone }) => (
        <div key={label}>
          <span className="label mb-1 block">{label}</span>
          <div className="flex flex-wrap gap-1.5">
            {levels?.length ? (
              levels.map((level) => (
                <span
                  key={level}
                  className={`rounded px-1.5 py-0.5 font-mono text-sm tabnum ${tone}`}
                >
                  {level}
                </span>
              ))
            ) : (
              <span className="text-sm text-fg-subtle">None on this side of the price</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The chart read behind a news verdict.
 *
 * This renders the same evidence the model was given — the three timeframes,
 * where price sits in its own multi-year range, and the bands price has
 * actually reversed in — rather than a summary of it. The panel it replaced
 * showed two rows of chips, which was most of the payload thrown away: it could
 * not say that a band was confirmed on three timeframes, that the weekly was
 * bearish underneath it, or that momentum had diverged from price.
 *
 * Falls back to those chips when an analysis predates the richer shape. Every
 * block renders nothing when its data is missing, so a partial payload degrades
 * instead of showing empty scaffolding.
 */
export default function TechnicalPanel({ technical }: { technical: TechnicalSignals }) {
  const reads = technical.timeframes ?? [];
  const resistance = technical.resistance_zones ?? [];
  const support = technical.support_zones ?? [];
  const inside = technical.inside_zones ?? [];
  const structure = technical.structure;

  if (!reads.length && !resistance.length && !support.length) {
    return <LegacyLevels technical={technical} />;
  }

  const divergences = reads
    .filter((read) => read.rsi?.divergence)
    .map((read) => `${read.timeframe}: ${read.rsi?.divergence}`);
  const alignment = structure?.timeframe_alignment ?? null;
  const conflicting = alignment?.startsWith('conflicting') ?? false;

  return (
    <div className="space-y-3">
      <TimeframeGrid reads={reads} />

      {alignment && (
        <p
          className={`flex items-start gap-1.5 text-sm leading-relaxed ${
            conflicting ? 'text-warn' : 'text-fg-muted'
          }`}
        >
          {conflicting && <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
          <span>{alignment}</span>
        </p>
      )}

      {divergences.length > 0 && (
        <p className="text-sm leading-relaxed text-warn">
          <span className="label mr-1 text-warn">RSI divergence</span>
          {divergences.join(' · ')}
        </p>
      )}

      {structure && <RangeStrip structure={structure} price={technical.current_price} />}

      <ZoneLadder
        resistance={resistance}
        support={support}
        inside={inside}
        price={technical.current_price}
      />

      {technical.target_price && (
        <div className="border-t border-line pt-2">
          <span className="label mb-1 block">Model target range</span>
          <span className="font-mono text-md tabnum text-fg">{technical.target_price}</span>
        </div>
      )}

      {/* Every constraint here is one a reader would otherwise have to guess at,
          and each one has been wrong in this panel before: a band read as a
          price, a horizon read off the distance to spot, a two-year level
          mistaken for an all-time one. */}
      <p className="text-2xs leading-relaxed text-fg-subtle">
        Bands are areas price reversed in on 4h, 1d and 1w candles, capped at two years of history.
        Strength weighs how often and how recently price turned there, on what volume, and whether
        the band has flipped between support and resistance. Horizon comes from the longest
        timeframe that confirmed the band, not from its distance to the current price.
      </p>
    </div>
  );
}
