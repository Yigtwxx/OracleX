'use client';

import { API_BASE_URL } from '@/lib/api';
import { useTrackRecord } from '@/hooks/useTrackRecord';
import {
  bucketState,
  coverage,
  edgePoints,
  formatEdge,
  formatRate,
  horizonLabel,
  isEmpty,
  type HorizonBucket,
  type LabelledBucket,
  type ObservedBucket,
} from '@/lib/trackRecord';

/**
 * The live half of the accuracy page.
 *
 * A client island rather than a server component: the numbers come from the
 * running backend, and this page has to render — with an honest notice — on an
 * install where nothing is listening. The prose around it is static and stays
 * on the server so `page.tsx` can still export `metadata`.
 *
 * Every cell that could show a number the backend declined to state goes
 * through `lib/trackRecord`. Nothing here divides, rounds or compares on its
 * own.
 */

function StateNote({ children }: { children: React.ReactNode }) {
  return <p className="mt-4 font-mono text-2xs text-fg-subtle">{children}</p>;
}

/** The dash a withheld figure leaves, with the reason attached for a reader. */
function Withheld({ n, minSamples }: { n: number; minSamples: number }) {
  return (
    <span
      className="text-fg-subtle"
      title={
        n === 0
          ? 'Nothing has been measured at this horizon yet.'
          : `${n} scored ${n === 1 ? 'call' : 'calls'} — below the ${minSamples} needed to state a rate.`
      }
    >
      —
    </span>
  );
}

function RateCell({ bucket, minSamples }: { bucket: HorizonBucket; minSamples: number }) {
  const state = bucketState(bucket);
  if (state !== 'reported') return <Withheld n={bucket.n} minSamples={minSamples} />;
  return <span className="text-fg">{formatRate(bucket.hit_rate)}</span>;
}

function EdgeCell({ bucket }: { bucket: HorizonBucket }) {
  const points = edgePoints(bucket);
  if (points === null) return <span className="text-fg-subtle">—</span>;
  return (
    <span className={points > 0 ? 'text-up' : points < 0 ? 'text-down' : 'text-fg-muted'}>
      {formatEdge(points)}
    </span>
  );
}

function LabelledTable({
  caption,
  rows,
  labelOf,
  minSamples,
}: {
  caption: string;
  rows: readonly LabelledBucket[];
  labelOf: (row: LabelledBucket) => string;
  minSamples: number;
}) {
  const populated = rows.filter((row) => row.n > 0);
  if (!populated.length) return null;

  return (
    <div className="mt-8">
      <h3 className="font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">{caption}</h3>
      <div className="custom-scrollbar mt-3 overflow-x-auto">
        <table className="w-full min-w-[380px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
              <th className="py-2 pr-4 font-normal">Group</th>
              <th className="py-2 pr-4 text-right font-normal">Calls</th>
              <th className="py-2 text-right font-normal">Hit rate</th>
            </tr>
          </thead>
          <tbody className="font-mono text-2xs tabnum">
            {populated.map((row) => (
              <tr key={labelOf(row)} className="border-b border-line/60">
                <td className="py-2 pr-4 text-fg-muted">{labelOf(row)}</td>
                <td className="py-2 pr-4 text-right text-fg-muted">{row.n}</td>
                <td className="py-2 text-right">
                  {row.hit_rate === null ? (
                    <Withheld n={row.n} minSamples={minSamples} />
                  ) : (
                    <span className="text-fg">{formatRate(row.hit_rate)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ObservedRow({ bucket }: { bucket: ObservedBucket }) {
  if (!bucket.n) return <span className="text-fg-subtle">—</span>;
  return (
    <span className="text-fg-muted">
      {bucket.bullish}/{bucket.bearish}/{bucket.neutral}
    </span>
  );
}

export default function TrackRecordBoard() {
  const { summary, loading, unreachable } = useTrackRecord();

  if (loading) {
    return <StateNote>Reading the record…</StateNote>;
  }

  // No fabricated board. Zeros would read as "the model got nothing right",
  // which is a claim about accuracy rather than a report about connectivity.
  if (unreachable || !summary) {
    return (
      <StateNote>
        The record could not be read — this page is served by a running instance, and none answered.
        Nothing is inferred in its place.
      </StateNote>
    );
  }

  const { totals, min_samples: minSamples } = summary;
  const done = coverage(totals);

  if (isEmpty(summary)) {
    return (
      <StateNote>
        Nothing has been measured yet. {totals.predictions} verdicts are on record and the shortest
        horizon closes a day after the call that made it.
      </StateNote>
    );
  }

  return (
    <div className="mt-6">
      <div className="custom-scrollbar overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-left">
          <caption className="sr-only">
            Directional hit rate by horizon, with the best fixed answer beside it
          </caption>
          <thead>
            <tr className="border-b border-line font-mono text-2xs uppercase tracking-[0.08em] text-fg-subtle">
              <th className="py-2 pr-4 font-normal">Horizon</th>
              <th className="py-2 pr-4 text-right font-normal">Calls</th>
              <th className="py-2 pr-4 text-right font-normal">Hit rate</th>
              <th className="py-2 pr-4 text-right font-normal">Best fixed answer</th>
              <th className="py-2 pr-4 text-right font-normal">Edge</th>
              <th className="py-2 text-right font-normal" title="bullish / bearish / neutral">
                Market
              </th>
            </tr>
          </thead>
          <tbody className="font-mono text-2xs tabnum">
            {summary.directional.by_horizon.map((bucket, index) => (
              <tr key={bucket.horizon_days} className="border-b border-line/60">
                <td className="py-2 pr-4 text-fg-muted">{horizonLabel(bucket.horizon_days)}</td>
                <td className="py-2 pr-4 text-right text-fg-muted">{bucket.n}</td>
                <td className="py-2 pr-4 text-right">
                  <RateCell bucket={bucket} minSamples={minSamples} />
                </td>
                <td className="py-2 pr-4 text-right">
                  {bucket.baseline_rate === null || bucket.baseline_rate === undefined ? (
                    <Withheld n={bucket.n} minSamples={minSamples} />
                  ) : (
                    <span className="text-fg-muted">
                      {formatRate(bucket.baseline_rate)}
                      {bucket.baseline_direction ? ` ${bucket.baseline_direction}` : ''}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4 text-right">
                  <EdgeCell bucket={bucket} />
                </td>
                <td className="py-2 text-right">
                  <ObservedRow bucket={summary.observed[index]} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <StateNote>
        {summary.directional.overall.n} directional calls scored ·{' '}
        {formatRate(summary.directional.overall.hit_rate)} pooled across every horizon ·{' '}
        {totals.pending} due and unmeasured
        {done !== null ? ` · ${formatRate(done)} of due horizons closed` : ''}
        {totals.unmeasurable ? ` · ${totals.unmeasurable} unmeasurable` : ''}
      </StateNote>

      <p className="mt-4 text-md text-fg-muted">
        A rate is printed only where at least {minSamples} calls have been scored; everywhere else
        the count stands alone. Neutral verdicts are counted separately and never enter the figure
        above — staying inside the flat band is the easiest of the three claims and the one the
        model reaches for most often. The horizons are measured from the moment the verdict existed,
        not from when the article was published, so a move that had already happened cannot be
        credited to the call; the baseline is the last close before that day.
        {summary.excluded.keyword_fallback_predictions > 0 ? (
          <>
            {' '}
            {summary.excluded.keyword_fallback_predictions} verdicts are excluded entirely: no model
            was reachable and the direction came from a word count over the headline.
          </>
        ) : null}
      </p>

      <LabelledTable
        caption="By materiality"
        rows={summary.by_materiality}
        labelOf={(row) => row.materiality ?? '—'}
        minSamples={minSamples}
      />
      <LabelledTable
        caption="By stated confidence"
        rows={summary.by_confidence}
        labelOf={(row) => row.band ?? '—'}
        minSamples={minSamples}
      />

      <p className="mt-8 font-mono text-2xs text-fg-subtle">
        <a
          className="underline decoration-dotted underline-offset-4 hover:text-fg"
          href={`${API_BASE_URL}/api/track-record/export.csv`}
        >
          Download the whole record (CSV)
        </a>{' '}
        · one row per call and horizon, unresolved calls included
        {summary.pipeline_versions.length > 1
          ? ` · ${summary.pipeline_versions.length} pipeline versions`
          : ''}
      </p>
    </div>
  );
}
