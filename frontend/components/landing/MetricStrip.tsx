import { LLM } from '@/lib/generated/repo-facts';

/** Two words each, and the same two-word shape across all three. Longer labels
 *  turned the strip into a row of half-sentences at three different lengths,
 *  which reads as a list of features rather than as a specification.
 *
 *  The provider count is read rather than written. It said fourteen for as long
 *  as anyone had counted the presets by eye, and one of those presets is the
 *  bring-your-own-base-URL escape hatch rather than a provider — exactly the
 *  kind of figure that is wrong the moment a row is added. */
const METRICS: readonly { readonly value: string; readonly label: string }[] = [
  { value: '3', label: 'analysis passes' },
  { value: String(LLM.presets), label: 'model providers' },
  { value: 'RAG', label: 'vector memory' },
];

/** The proof line under the hero: three figures, no adjectives. The values are
 *  either a count or the name of the thing itself — a version number is the one
 *  kind of value here that means nothing to a reader seeing the page first. */
export default function MetricStrip() {
  return (
    <dl className="flex flex-wrap items-baseline gap-x-8 gap-y-3 font-mono text-xs">
      {METRICS.map((metric) => (
        <div key={metric.label} className="flex items-baseline gap-2">
          <dt className="sr-only">{metric.label}</dt>
          <dd className="flex items-baseline gap-2">
            <span className="text-md font-semibold tabnum text-fg">{metric.value}</span>
            <span className="text-fg-subtle">{metric.label}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
