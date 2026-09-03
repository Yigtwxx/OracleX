'use client';

import type { MacroRegime } from '@/lib/api';
import AiNote from '@/components/ui/AiNote';

interface RegimeCardProps {
  regime: MacroRegime | undefined;
  isLoading: boolean;
}

/**
 * The board's one-line answer: risk-on, risk-off, or neither.
 *
 * The label and the readings under it are computed on the server and are always
 * present. The sentence is not, and the card is laid out so that its absence
 * costs a line rather than the panel.
 *
 * The "does not measure" footnote is not boilerplate to skim past. This
 * application carries no volatility, rates or credit feed at all, so a
 * cross-asset call made from equities, the dollar and two metals can be right
 * about everything it can see and still miss the day's actual driver. Saying
 * which instruments were on the desk is the difference between a partial read
 * and an overclaiming one.
 */
export default function RegimeCard({ regime, isLoading }: RegimeCardProps) {
  if (isLoading) return <div className="surface h-[92px] shimmer" />;

  // Not an error state: too many feeds were missing to score three votes, and
  // the page's own board panel is already reporting whatever went wrong.
  if (!regime || regime.label === 'Unavailable') return null;

  const tone = regime.score > 0 ? 'text-up' : regime.score < 0 ? 'text-down' : 'text-fg-muted';

  return (
    <div className="surface ai-surface p-4 flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
        <span className={`text-md font-semibold ${tone}`}>{regime.label}</span>

        {regime.components.map((component) => (
          <span key={component.key} className="text-xs text-fg-subtle font-mono tabnum">
            {component.reading}
          </span>
        ))}

        {regime.stale && <span className="text-2xs text-warn">replayed from cache</span>}
      </div>

      <AiNote aiNote={regime.note} />

      <p className="text-2xs text-fg-subtle">
        Does not measure: {regime.not_measured.join(', ')}.
        {regime.unavailable.length > 0 && ` Unreadable today: ${regime.unavailable.join(', ')}.`}
      </p>
    </div>
  );
}
