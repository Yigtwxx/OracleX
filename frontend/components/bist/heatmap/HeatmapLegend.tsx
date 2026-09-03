'use client';

import { BIST_METRIC_CONFIG, type BistHeatMetric } from '@/lib/bist-heatmap';
import { UNKNOWN_BUCKET } from '@/lib/heatmap-scale';

/**
 * Rendered from the same array `bucketForTile` walks.
 *
 * Not a hand-written row of swatches. The crypto board's legend used to be one
 * and it drifted from the colour function — it showed a swatch the scale never
 * produced and omitted two it did — which is why the scale is data and a test
 * pins that the two still agree.
 */
export default function HeatmapLegend({ metric }: { metric: BistHeatMetric }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-2xs">
      {BIST_METRIC_CONFIG[metric].scale.map((bucket) => (
        <span key={bucket.className + bucket.label} className="flex items-center gap-1">
          <span className={`h-3 w-3 rounded ${bucket.className}`} aria-hidden="true" />
          <span className="text-fg-muted">{bucket.label}</span>
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span className={`h-3 w-3 rounded ${UNKNOWN_BUCKET.className}`} aria-hidden="true" />
        <span className="text-fg-muted">Veri yok</span>
      </span>
    </div>
  );
}
